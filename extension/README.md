# Slipwright for VS Code

Watch and steer Slipwright developments without leaving the editor.

- **Projects** in the activity bar: every project, its developments and the state each one
  is in. A gate waiting for you is marked, and the status bar says how many there are.
- **New development**: describe what you want; the Product Owner and the Architect answer
  and the work list waits for you in the app.
- **Open in browser**: the project or the development, on your Slipwright server.

## Signing in

Run **Slipwright: Sign in** and give the server address, your username and your password.
The extension issues an API token for this editor, keeps it in VS Code's secret storage and
uses nothing else afterwards. **Slipwright: Sign out** forgets it.

## Settings

| Setting | What it does |
|---|---|
| `slipwright.endpoint` | The server this extension talks to (`http://localhost:8500` by default). |
| `slipwright.refreshSeconds` | How often the tree is refreshed while the window is open. |

## Building it

```
npm install
npm run typecheck && npm test && npm run build
npx @vscode/vsce package --no-dependencies   # slipwright-0.1.0.vsix
```

Install the file with **Extensions → … → Install from VSIX…**, or
`code --install-extension slipwright-0.1.0.vsix`.
