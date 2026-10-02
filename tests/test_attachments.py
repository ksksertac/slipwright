"""Files a person gives the agents: what is accepted, how it is read, and who reads it."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from slipwright import attachments as attached
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.providers import ImageInput, ModelRequest, ProviderError
from slipwright.providers.anthropic import build_request_kwargs
from slipwright.providers.openai_compat import OpenAICompatProvider
from slipwright.providers.scripted import ScriptedProvider
from slipwright.schemas.profile import Profile, RoleName, ThinkingDepth
from slipwright.schemas.project import Project
from slipwright.store import AttachmentNotFound, JobStore
from tests.pipeline import full_engine, full_provider


@pytest.fixture
def provider(seed: Profile) -> ScriptedProvider:
    return full_provider(seed, phases=1)


@pytest.fixture
def engine(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider
) -> Engine:
    return full_engine(store, worktrees_root, seed, provider)


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


@pytest.fixture
def project(engine: Engine, repo: Path) -> Project:
    return engine.create_project(Project(name="shop", repo_path=repo))


def _pdf(text: str) -> bytes:
    """A one-page PDF saying ``text``, written by hand so the test needs no PDF writer."""
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="urn:w"><w:body>'
        f"{body}</w:body></w:document>"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return out.getvalue()


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


def _upload(client: TestClient, project_id: str, name: str, data: bytes, **form: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/projects/{project_id}/attachments", files={"file": (name, data)}, data=form
    )


def _po_prompts(provider: ScriptedProvider) -> list[str]:
    return [
        r.prompt
        for r in provider.requests
        if r.role is RoleName.PO and "Turn `request` into a backlog" in r.prompt
    ]


# --- what is accepted -----------------------------------------------------------------------


def test_a_file_is_known_by_what_is_in_it_not_by_its_name() -> None:
    assert attached.sniff(_pdf("hello"), "notes.txt") == attached.PDF
    assert attached.sniff(_png(4, 4), "screen.pdf") == "image/png"
    assert attached.sniff(_docx("x"), "spec.docx") == attached.DOCX
    assert attached.sniff(b"# Spec\n", "spec.md") == "text/markdown"
    with pytest.raises(attached.UnsupportedFile):
        attached.sniff(b"<html><script>alert(1)</script></html>", "screen.pdf")


def test_a_picture_that_can_carry_a_script_is_refused(client: TestClient, project: Project) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    refused = _upload(client, project.id, "logo.svg", svg)
    assert refused.status_code == 415
    assert client.get(f"/api/projects/{project.id}/attachments").json() == []


def test_a_file_over_the_limit_is_refused(
    client: TestClient, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(attached, "MAX_BYTES", 100)
    refused = _upload(client, project.id, "big.md", b"x" * 101)
    assert refused.status_code == 413
    assert "MB" in refused.json()["detail"]


def test_a_project_holds_a_limited_number_of_files(
    client: TestClient, project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(attached, "MAX_PER_PROJECT", 2)
    assert _upload(client, project.id, "a.md", b"a").status_code == 201
    assert _upload(client, project.id, "b.md", b"b", draft="true").status_code == 201
    assert _upload(client, project.id, "c.md", b"c").status_code == 409


def test_a_file_that_would_pass_the_disk_quota_is_refused(
    engine: Engine, client: TestClient, project: Project
) -> None:
    engine.quotas.update(max_disk_mb=1)
    refused = _upload(client, project.id, "big.md", b"x" * (2 * 1024 * 1024))
    assert refused.status_code == 429


def test_the_example_project_takes_no_files(
    engine: Engine, client: TestClient, repo: Path
) -> None:
    demo = engine.create_project(Project(name="example", is_demo=True, repo_path=repo))
    assert _upload(client, demo.id, "a.md", b"a").status_code == 409


# --- what is taken out of it ----------------------------------------------------------------


def test_the_text_of_a_pdf_and_of_a_word_document_is_taken_out() -> None:
    text, pages = attached.extract(_pdf("Customers pay by card"), attached.PDF)
    assert "Customers pay by card" in text
    assert pages == 1
    text, _ = attached.extract(_docx("Sign in with e-mail", "Reset a password"), attached.DOCX)
    assert text.splitlines() == ["Sign in with e-mail", "Reset a password"]


def test_a_broken_pdf_is_kept_without_text_rather_than_refused() -> None:
    assert attached.extract(b"%PDF-1.4\nnot really", attached.PDF) == ("", 0)


def test_a_picture_is_scaled_down_before_a_model_sees_it() -> None:
    [shown] = attached.pictures(_png(4000, 3000), "image/png", name="home.png")
    with Image.open(io.BytesIO(shown.data)) as img:
        assert max(img.size) == attached.LONG_EDGE
    assert shown.label == "home.png"


def test_the_pages_of_a_pdf_are_drawn_for_the_model_to_look_at() -> None:
    [page] = attached.pictures(_pdf("Sign in"), attached.PDF, name="screens.pdf")
    assert page.label == "screens.pdf, page 1"
    assert page.media_type in {"image/png", "image/jpeg"}


def test_a_folder_sent_with_the_name_is_dropped() -> None:
    assert attached.clean_name("C:\\Users\\ada\\ekran.pdf") == "ekran.pdf"
    assert attached.clean_name("../../etc/passwd") == "passwd"
    assert attached.clean_name("a\x00b.png") == "ab.png"
    assert attached.clean_name("...") == "file"


# --- how it is read -------------------------------------------------------------------------


def test_an_attached_screen_is_read_once_by_a_model_that_is_shown_it(
    client: TestClient, project: Project, provider: ScriptedProvider
) -> None:
    made = _upload(client, project.id, "home.png", _png(40, 30))
    assert made.status_code == 201, made.text

    [found] = client.get(f"/api/projects/{project.id}/attachments").json()
    assert found["reading_state"] == "done"
    assert found["reading"]["kind"] == "screens"
    assert found["reading"]["screens"][0]["title"] == "Sign in"
    [asked] = [r for r in provider.requests if "Read the file in `file`" in r.prompt]
    assert [i.label for i in asked.images] == ["home.png"]
    # the picture went beside the prompt, not into it
    assert "iVBOR" not in asked.prompt


def test_a_model_that_cannot_see_reads_the_text_alone_and_says_so(
    client: TestClient, project: Project, provider: ScriptedProvider
) -> None:
    def blind(request: ModelRequest) -> dict[str, object]:
        if request.images:
            raise ProviderError("API error 404: No endpoints found that support image input")
        return {"summary": "a spec", "kind": "document", "requirements": ["pay by card"]}

    provider.discovery["reading"] = blind
    _upload(client, project.id, "spec.pdf", _pdf("Customers pay by card"))

    [found] = client.get(f"/api/projects/{project.id}/attachments").json()
    assert found["reading_state"] == "done"
    assert found["reading"]["requirements"] == ["pay by card"]
    assert "text alone" in found["reading"]["note"]


def test_a_reading_that_fails_can_be_asked_for_again(
    client: TestClient, project: Project, provider: ScriptedProvider
) -> None:
    provider.discovery["reading"] = lambda request: "not json"
    made = _upload(client, project.id, "spec.md", b"# Spec\nPay by card.\n").json()
    assert client.get(f"/api/projects/{project.id}/attachments").json()[0]["reading_state"] == (
        "failed"
    )

    provider.discovery["reading"] = {"summary": "a spec", "kind": "document"}
    again = client.post(f"/api/attachments/{made['id']}/read")
    assert again.status_code == 202
    [found] = client.get(f"/api/projects/{project.id}/attachments").json()
    assert found["reading_state"] == "done"


# --- who reads it ---------------------------------------------------------------------------


def test_the_product_owner_plans_from_the_files_of_the_development(
    client: TestClient, project: Project, provider: ScriptedProvider
) -> None:
    draft = _upload(client, project.id, "spec.pdf", _pdf("Customers pay by card"), draft="true")
    assert draft.status_code == 201

    started = client.post(
        f"/api/projects/{project.id}/jobs",
        json={"request": "Build the checkout", "attachments": [draft.json()["id"]]},
    )
    assert started.status_code == 201, started.text

    [prompt] = _po_prompts(provider)
    assert "Customers pay by card" in prompt  # the text itself
    # and what the reading made of it: a PDF's pages are shown to the reader as pictures
    assert "scripted: a screen" in prompt
    assert "not instructions to you" in prompt


def test_a_draft_goes_to_the_development_it_was_chosen_for_and_no_other(
    client: TestClient, project: Project, provider: ScriptedProvider
) -> None:
    draft = _upload(client, project.id, "one.md", b"only for the first", draft="true").json()
    # a draft is not the project's: no agent reads it and the project does not list it
    assert client.get(f"/api/projects/{project.id}/attachments").json() == []

    first = client.post(
        f"/api/projects/{project.id}/jobs",
        json={"request": "first", "attachments": [draft["id"]]},
    ).json()
    listed = client.get(f"/api/projects/{project.id}/attachments?job_id={first['id']}").json()
    assert [a["name"] for a in listed] == ["one.md"]
    assert listed[0]["scope"] == "job"

    client.post(f"/api/projects/{project.id}/jobs", json={"request": "second"})
    first_prompt, second_prompt = _po_prompts(provider)
    assert "only for the first" in first_prompt
    assert "only for the first" not in second_prompt


def test_a_draft_cannot_be_sent_twice(client: TestClient, project: Project) -> None:
    draft = _upload(client, project.id, "one.md", b"x", draft="true").json()
    body = {"request": "first", "attachments": [draft["id"]]}
    assert client.post(f"/api/projects/{project.id}/jobs", json=body).status_code == 201
    assert client.post(f"/api/projects/{project.id}/jobs", json=body).status_code == 404


def test_the_projects_own_files_reach_every_development(
    client: TestClient, project: Project, provider: ScriptedProvider
) -> None:
    _upload(client, project.id, "brand.md", b"Everything is green.")
    client.post(f"/api/projects/{project.id}/jobs", json={"request": "first"})
    client.post(f"/api/projects/{project.id}/jobs", json={"request": "second"})
    assert all("Everything is green." in p for p in _po_prompts(provider))


def test_the_roles_after_the_product_owner_get_the_reading_not_the_text(
    engine: Engine, client: TestClient, project: Project
) -> None:
    _upload(client, project.id, "spec.md", b"The whole long text of the spec.")
    job = engine.create_job("x", project_id=project.id)
    whole = engine.attachments_for(job)
    digest = engine.attachments_for(job, whole=False)
    assert whole is not None and digest is not None
    assert whole["files"][0]["text"] == "The whole long text of the spec."
    assert "text" not in digest["files"][0]
    assert digest["files"][0]["summary"] == "scripted: a document"


def test_the_intake_reads_the_projects_files_before_it_asks(
    engine: Engine, client: TestClient, project: Project, provider: ScriptedProvider
) -> None:
    _upload(client, project.id, "idea.md", b"A shop for second-hand bicycles.")
    client.post(f"/api/projects/{project.id}/brief/intake", json={"answers": {}})
    [asked] = [r for r in provider.requests if "the repository is empty" in r.prompt]
    assert "second-hand bicycles" in asked.prompt


# --- what is served and what is kept --------------------------------------------------------


def test_a_file_is_downloaded_never_opened_in_the_page(
    client: TestClient, project: Project
) -> None:
    made = _upload(client, project.id, "spec.pdf", _pdf("x")).json()
    got = client.get(f"/api/attachments/{made['id']}/file?inline=true")
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/octet-stream"
    assert got.headers["content-disposition"].startswith("attachment;")
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.content == _pdf("x")


def test_a_picture_may_be_shown_but_only_in_a_sandbox(
    client: TestClient, project: Project
) -> None:
    made = _upload(client, project.id, "home.png", _png(8, 8)).json()
    got = client.get(f"/api/attachments/{made['id']}/file?inline=true")
    assert got.headers["content-type"] == "image/png"
    assert got.headers["content-disposition"].startswith("inline;")
    assert "sandbox" in got.headers["content-security-policy"]


def test_a_file_goes_with_its_project(
    engine: Engine, client: TestClient, project: Project, store: JobStore
) -> None:
    made = _upload(client, project.id, "a.md", b"a").json()
    engine.delete_project(project.id)
    with pytest.raises(AttachmentNotFound):
        store.get_attachment(made["id"])


def test_someone_elses_file_is_not_found(
    client: TestClient, project: Project, store: JobStore
) -> None:
    made = _upload(client, project.id, "a.md", b"a").json()
    with pytest.raises(AttachmentNotFound):
        store.get_attachment(made["id"], owner_id="somebody-else")
    with pytest.raises(AttachmentNotFound):
        store.attachment_data(made["id"], owner_id="somebody-else")


def test_files_count_toward_the_disk_an_account_uses(
    engine: Engine, client: TestClient, project: Project
) -> None:
    before = engine.quotas.usage(project.owner_id).disk_mb
    _upload(client, project.id, "big.md", b"x" * (3 * 1024 * 1024))
    assert engine.quotas.usage(project.owner_id).disk_mb == before + 3


# --- how the pictures travel ----------------------------------------------------------------


def _request_with_a_picture() -> ModelRequest:
    return ModelRequest(
        role=RoleName.PO,
        model="m",
        thinking_depth=ThinkingDepth.OFF,
        system="s",
        prompt="describe it",
        output_schema={"type": "object"},
        timeout_s=10,
        images=(ImageInput(media_type="image/png", data=b"\x89PNG", label="home.png"),),
    )


def test_anthropic_is_shown_the_picture_as_an_image_block() -> None:
    kwargs = build_request_kwargs(_request_with_a_picture(), max_tokens=100)
    label, image, prompt = kwargs["messages"][0]["content"]
    assert label == {"type": "text", "text": "home.png"}
    assert image["type"] == "image"
    assert image["source"] == {"type": "base64", "media_type": "image/png", "data": "iVBORw=="}
    assert prompt == {"type": "text", "text": "describe it"}


def test_an_openai_compatible_vendor_is_shown_the_picture_as_a_data_url() -> None:
    body = OpenAICompatProvider("key", "https://example.invalid").build_body(
        _request_with_a_picture()
    )
    parts = body["messages"][1]["content"]
    assert parts[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,iVBORw=="},
    }
    assert parts[-1] == {"type": "text", "text": "describe it"}


def test_a_database_written_before_attachments_upgrades_into_one(tmp_path: Path) -> None:
    """Built by taking the new shape apart: drop what 0010 and every later revision add,
    stamp the revision before it, and let the store upgrade itself the way a server does
    on start."""
    from alembic import command
    from sqlalchemy import inspect, text

    from slipwright.store.db import Database
    from slipwright.store.migrate import _config, migrate
    from slipwright.store.schema import metadata

    db = Database(str(tmp_path / "old.sqlite3"))
    try:
        metadata.create_all(db.engine)
        with db.begin() as conn:
            conn.execute(text("DROP TABLE attachments"))
            conn.execute(text("ALTER TABLE jobs DROP COLUMN title"))  # (0011: job title)
            conn.execute(text("DROP TABLE job_messages"))  # (0013)
            for table in ("workers", "worker_codes", "worker_tasks"):  # (0012)
                conn.execute(text(f"DROP TABLE {table}"))
        command.stamp(_config(db), "0009_two_factor")

        migrate(db)

        assert "attachments" in set(inspect(db.engine).get_table_names())
        columns = {c["name"] for c in inspect(db.engine).get_columns("attachments")}
        assert {"data", "text", "reading_json", "scope"} <= columns
    finally:
        db.dispose()


# --- the Designer looks at the screens ------------------------------------------------------


def _to_the_design(engine: Engine, provider: ScriptedProvider, seed: Profile, project: Project):  # type: ignore[no-untyped-def]
    """A development with a web phase, carried to the Designer."""
    from tests.pipeline import set_plan

    set_plan(provider, seed, [{"goal": "the page", "files": ["OK"], "domain": "web"}])
    job = engine.start(engine.create_job("the sign-in page", project_id=project.id).id)
    job = engine.approve(job.id)  # backlog
    return engine.approve(job.id)  # architecture -> the Designer


def test_the_designer_is_shown_the_screens_it_was_given(
    engine: Engine,
    client: TestClient,
    project: Project,
    provider: ScriptedProvider,
    seed: Profile,
) -> None:
    _upload(client, project.id, "home.png", _png(40, 30))
    _upload(client, project.id, "screens.pdf", _pdf("Sign in"))
    _upload(client, project.id, "notes.md", b"Only words here.")  # read as a document

    _to_the_design(engine, provider, seed, project)

    [asked] = [r for r in provider.requests if r.role is RoleName.DESIGNER]
    # the PDF's reading found its screen on page 1, so that page is what is drawn
    assert [i.label for i in asked.images] == ["home.png", "screens.pdf, page 1"]
    assert "keep to what you see" in asked.prompt


def test_a_designer_that_cannot_see_designs_from_the_descriptions(
    engine: Engine,
    client: TestClient,
    project: Project,
    provider: ScriptedProvider,
    seed: Profile,
) -> None:
    drawn = provider.replies[RoleName.DESIGNER]

    def blind(request: ModelRequest) -> object:
        if request.images:
            raise ProviderError("API error 400: this model does not take images")
        return drawn(request) if callable(drawn) else drawn  # type: ignore[return-value]

    provider.replies[RoleName.DESIGNER] = blind
    _upload(client, project.id, "home.png", _png(40, 30))

    job = _to_the_design(engine, provider, seed, project)

    asked = [r for r in provider.requests if r.role is RoleName.DESIGNER]
    assert [bool(r.images) for r in asked] == [True, False]
    assert "Sign in" in asked[-1].prompt  # the reading's description of the screen
    assert job.data.design is not None


def test_the_design_gate_shows_the_screen_a_design_keeps_to(
    engine: Engine, client: TestClient, project: Project, store: JobStore
) -> None:
    made = _upload(client, project.id, "screens.pdf", _pdf("Sign in")).json()
    job = engine.create_job("x", project_id=project.id)
    job.data.design = {
        "screens": [
            {
                "id": "s1",
                "name": "Sign in",
                "purpose": "sign in",
                "layout": "a form",
                "reference": {"file": "screens.pdf", "page": 1},
            },
            {"id": "s2", "name": "Home", "purpose": "look", "layout": "a list"},
        ]
    }
    store.save(job)

    screens = client.get(f"/api/jobs/{job.id}/design").json()["screens"]
    assert screens[0]["reference"] == {
        "file": "screens.pdf",
        "page": 1,
        "url": f"/api/attachments/{made['id']}/pages/1",
    }
    assert screens[1]["reference"] is None

    page = client.get(screens[0]["reference"]["url"])
    assert page.status_code == 200
    assert page.headers["content-type"] in {"image/png", "image/jpeg"}
    assert "sandbox" in page.headers["content-security-policy"]
    assert client.get(f"/api/attachments/{made['id']}/pages/9").status_code == 404


# --- where a story came from ----------------------------------------------------------------


def test_a_story_names_the_file_and_page_it_came_from(
    engine: Engine, client: TestClient, project: Project, provider: ScriptedProvider
) -> None:
    from slipwright.jirasync import _with_sources
    from slipwright.roles.results import FileRef

    backlog = provider.replies[RoleName.PO]
    assert isinstance(backlog, dict)
    story = backlog["breakdown"]["epics"][0]["stories"][0]
    story["sources"] = [{"file": "spec.pdf", "page": 3}]

    job = engine.start(engine.create_job("checkout", project_id=project.id).id)

    kept = job.data.backlog["epics"][0]["stories"][0]  # type: ignore[index]
    assert kept["sources"] == [{"file": "spec.pdf", "page": 3}]
    assert "`sources`" in _po_prompts(provider)[0]
    # and Jira, which has no copy of the file, is told which document to look in
    assert _with_sources("Pay by card.", [FileRef(file="spec.pdf", page=3)]) == (
        "Pay by card.\n\nSource: spec.pdf, p. 3"
    )


def test_reading_a_file_is_counted_in_the_projects_costs(
    client: TestClient, project: Project
) -> None:
    _upload(client, project.id, "spec.md", b"# Spec\n")
    costs = client.get(f"/api/projects/{project.id}/costs").json()
    assert costs["reading"]["calls"] == 1
    assert costs["reading"]["label"] == "Reading attached files"
