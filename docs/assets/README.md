---
status: ACTIVE
version: 1.1
---

# Envman visual assets

The Envman identity uses a bracketed equals mark, mineral teal, deep ink, and a high-visibility signal color. Original visuals are authored as SVG so the repository stays crisp at any size.

## Files

- `brand-mark.svg` and `favicon.svg` provide the compact symbol.
- `logo-light.svg` and `logo-dark.svg` are color-scheme variants for the repository README and other wide placements.
- `terminal-preview.svg` is the detailed synthetic product view; `terminal-preview-mobile.svg` rearranges the same sample state into a readable narrow layout.
- `social-preview.svg` is the editable 1280 by 640 source for `social-preview.png`, used as the GitHub repository social preview.

## Regenerating the social image

Run `python3 scripts/render_visual_assets.py` as a normal user with Google Chrome or Chromium installed. The script preserves the browser sandbox, renders `social-preview.svg` headlessly at exactly 1280 by 640 pixels, and embeds title, creator, source, copyright, and private-asset rights metadata in the PNG. The SVG remains the editable source. Do not use a screenshot containing real environment values.

After changing the image, upload `social-preview.png` under **Settings → General → Social preview → Edit → Upload an image** in the [GitHub repository settings](https://github.com/CruxExperts/EnvMan/settings). Committing the PNG alone does not update that setting. Confirm the new preview appears after the upload.

Copyright © 2026 Crux Experts LLC. See the metadata embedded in each asset for the complete asset notice. Envman source code remains available under the repository's [MIT License](../../LICENSE); the logo, previews, and other original visual assets are private property and have separate rights.
