---
status: ACTIVE
version: 2.0
last_updated: "2026-10-19"
---

# Envman visual assets

The Envman identity pairs a bracketed equals sign with mineral teal, pale mint,
soft ivory, and a restrained lime accent. Compact logos stay flat and readable;
campaign images use a sculpted-metal interpretation of the same symbol. The
product promise is **Your environment, in order.**

## Choose the right asset

| Placement | File | Export size |
| --- | --- | --- |
| GitHub social preview and 2:1 link cards | [social-preview.png](social-preview.png) | 1280 × 640 |
| Repository README and wide banners | [github-banner.png](github-banner.png) | 1600 × 640 |
| Square social posts and narrow README layouts | [social-square.png](social-square.png) | 1080 × 1080 |
| Application/profile mark | [brand-mark.svg](brand-mark.svg), [PNG](brand-mark.png) | Vector; 1024 × 1024 |
| Light-background wordmark | [logo-light.svg](logo-light.svg), [PNG](logo-light.png) | Vector; 1120 × 256 |
| Dark-background wordmark | [logo-dark.svg](logo-dark.svg), [PNG](logo-dark.png) | Vector; 1120 × 256 |
| Small application icon | [favicon.svg](favicon.svg), [PNG](favicon.png) | Vector; 64 × 64 |
| Generated campaign artwork master | [brand-artwork.webp](brand-artwork.webp) | 1536 × 1024 |
| Reusable asset collection | [envman-brand-assets-v1.0.0.zip](envman-brand-assets-v1.0.0.zip) | Sources, exports, manifest, renderer |

Use the flat mark rather than the sculpted artwork below 128 pixels. Keep clear
space around the mark, preserve proportions, and do not add shadows to the flat
logos. Wordmark PNGs have transparent backgrounds. GitHub repository identity
uses the owner account avatar; there is no separate repository-avatar setting.
The application mark is supplied for project-specific placements, not as a
replacement for the organization's account avatar.

`terminal-preview.svg` and `terminal-preview-mobile.svg` remain synthetic product
illustrations, not photographs or screenshots of a live user session. Their
sample state is independent of the campaign artwork.

## Regenerate and package

Run from the repository root as a normal user:

```bash
python3 scripts/render_visual_assets.py --all
```

The existing renderer owns the seven coordinated SVG sources and PNG exports.
It embeds the artwork master into campaign SVGs so they remain self-contained,
then renders with headless Google Chrome or Chromium without disabling the
browser sandbox. It also creates the versioned ZIP, including this guide and
[asset-manifest.json](asset-manifest.json). No image API call or Python imaging
dependency is needed to reproduce exports from the committed master.

For a PNG-only render of the committed social SVG, the original command remains:

```bash
python3 scripts/render_visual_assets.py
```

Change layout, colors, typography, or mark geometry in the renderer, not in its
generated SVGs. Change the campaign master only when intentionally revising the
art direction. The independent terminal illustrations remain editable SVGs.
PNG exports carry title, creator, source, copyright and rights fields, plus XMP.
SVG and WebP sources carry the corresponding ownership metadata. The manifest
records the generation prompt and provenance; generation does not establish
trademark clearance.

## GitHub social preview

The public repository was checked on 2026-10-19. Its Open Graph and Twitter card
metadata both pointed to a working custom 1280 × 640 preview, using the earlier
terminal-catalog design. The new card is prepared in `social-preview.png`.

Uploading is a separate publication step: **Settings → General → Social preview
→ Edit → Upload an image** in the [repository settings](https://github.com/CruxExperts/EnvMan/settings).
Committing or pushing a PNG does not update that setting. After an authorized
upload, inspect the public repository's `og:image` and `twitter:image` URLs and
open the served image to confirm the new artwork. Social platforms may retain
cached cards after GitHub has updated.

## Rights

Copyright © 2026 Crux Experts LLC. https://www.cruxexperts.com/

Private asset. Property of Crux Experts LLC. Use, reproduction, modification,
distribution, or publication without prior written permission is prohibited.

Envman source code remains available under the repository's [MIT License](../../LICENSE).
Original logo, preview, and campaign assets have the separate rights above;
the source-code license does not grant rights to those assets.
