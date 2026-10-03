// build/icon.png from the web app's logo, at the 512 px electron-builder wants to derive
// the .ico and .icns from. Run inside Electron (npm run icon) for its image scaler, so the
// repository needs no image library for a file made once.
const { app, nativeImage } = require("electron");
const { mkdirSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");

app.whenReady().then(() => {
  const root = join(__dirname, "..");
  const logo = nativeImage.createFromPath(join(root, "resources", "logo.png"));
  mkdirSync(join(root, "build"), { recursive: true });
  writeFileSync(join(root, "build", "icon.png"), logo.resize({ width: 512, height: 512, quality: "best" }).toPNG());
  app.quit();
});
