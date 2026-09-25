"""What each model costs, mixed into ``JobStore``.

One row per provider and model. ``source`` says where the figure came from: ``litellm``
for the daily fetch, ``manual`` for a price a person typed in. A manual row is never
overwritten by the fetch — an installation with its own negotiated rates keeps them.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from slipwright.store.db import Database, one, rows
from slipwright.store.schema import model_prices

_COLUMNS = ("provider", "model", "input_usd", "output_usd", "source", "at")
_ON_CONFLICT = ("input_usd", "output_usd", "source", "at")


class PriceStoreMixin:
    """Requires ``db`` on the host class."""

    db: Database

    def put_price(
        self,
        provider: str,
        model: str,
        *,
        input_usd: float,
        output_usd: float,
        source: str = "manual",
    ) -> None:
        from slipwright.schemas.job import utcnow

        with self.db.begin() as conn:
            conn.execute(
                self.db.upsert(
                    model_prices,
                    {
                        "provider": provider,
                        "model": model,
                        "input_usd": input_usd,
                        "output_usd": output_usd,
                        "source": source,
                        "at": utcnow().isoformat(),
                    },
                    key=["provider", "model"],
                    update=list(_ON_CONFLICT),
                )
            )

    def put_prices(self, fetched: list[dict[str, object]], *, source: str) -> int:
        """Write a whole fetched table. Rows whose (provider, model) a person entered by
        hand are left alone, which is the point of keeping ``source``."""
        from slipwright.schemas.job import utcnow

        at = utcnow().isoformat()
        with self.db.begin() as conn:
            manual = {
                (r["provider"], r["model"])
                for r in rows(
                    conn.execute(
                        select(model_prices.c.provider, model_prices.c.model).where(
                            model_prices.c.source == "manual"
                        )
                    )
                )
            }
            wanted = [
                {
                    "provider": row["provider"],
                    "model": row["model"],
                    "input_usd": row["input_usd"],
                    "output_usd": row["output_usd"],
                    "source": source,
                    "at": at,
                }
                for row in fetched
                if (row["provider"], row["model"]) not in manual
            ]
            if wanted:
                conn.execute(
                    self.db.upsert(
                        model_prices,
                        wanted,
                        key=["provider", "model"],
                        update=list(_ON_CONFLICT),
                    )
                )
        return len(wanted)

    def get_price(self, provider: str, model: str) -> dict[str, object] | None:
        with self.db.connect() as conn:
            return one(
                conn.execute(
                    select(model_prices).where(
                        model_prices.c.provider == provider, model_prices.c.model == model
                    )
                )
            )

    def list_prices(self, provider: str | None = None) -> list[dict[str, object]]:
        query = select(model_prices).order_by(model_prices.c.provider, model_prices.c.model)
        if provider:
            query = query.where(model_prices.c.provider == provider)
        with self.db.connect() as conn:
            return [dict(r) for r in rows(conn.execute(query))]

    def delete_price(self, provider: str, model: str) -> None:
        with self.db.begin() as conn:
            conn.execute(
                delete(model_prices).where(
                    model_prices.c.provider == provider, model_prices.c.model == model
                )
            )


__all__ = ["PriceStoreMixin"]
