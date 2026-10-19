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
| GitHub social preview, desktop README hero, and 2:1 link cards | [social-preview.png](social-preview.png) | 1280 × 640 |
| Extra-wide banners | [github-banner.png](github-banner.png) | 1600 × 640 |
| Square social posts and narrow README layouts | [social-square.png](social-square.png) | 1080 × 1080 |
| Application/profile mark | [brand-mark.svg](brand-mark.svg), [PNG](brand-mark.png) | Vector; 1024 × 1024 |
| Light-background wordmark | [logo-light.svg](logo-light.svg), [PNG](logo-light.png) | Vector; 1120 × 256 |
| Dark-background wordmark | [logo-dark.svg](logo-dark.svg), [PNG](logo-dark.png) | Vector; 1120 × 256 |
| Small application icon | [favicon.svg](favicon.svg), [PNG](favicon.png) | Vector; 64 × 64 |
| Generated campaign artwork master | [brand-artwork.webp](brand-artwork.webp) | 1536 × 1024 |
| Real product screenshot and reduced-motion fallback | [terminal-preview.png](terminal-preview.png) | 1368 × 958 |
| Real usage walkthrough, lossless animation | [terminal-walkthrough.webp](terminal-walkthrough.webp) | 1368 × 958; 31.37 seconds |
| Animated fallback | [terminal-walkthrough.gif](terminal-walkthrough.gif) | 1368 × 958; 31.37 seconds |
| Reusable asset collection | [envman-brand-assets-v1.0.0.zip](envman-brand-assets-v1.0.0.zip) | Sources, exports, manifest, renderer |

Use the flat mark rather than the sculpted artwork below 128 pixels. Keep clear
space around the mark, preserve proportions, and do not add shadows to the flat
logos. Wordmark PNGs have transparent backgrounds. GitHub repository identity
uses the owner account avatar; there is no separate repository-avatar setting.
The application mark is supplied for project-specific placements, not as a
replacement for the organization's account avatar.

The product screenshot and walkthrough are native captures of the actual Envman
0.1.12 interface running in WezTerm. Only the 48 demonstration variables are
synthetic; the interface, selection cursor, text entry, masking, and saved edit
are real. There is no generated interface or simulated mouse pointer.

The desktop README hero deliberately uses the exact social-preview PNG, not a
separately generated logo or illustration. The narrow README uses the square
composition of the same master. Keep these references aligned when changing the
brand; do not reintroduce the earlier lime-tile wordmark as the README hero.

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
art direction. Product screenshots and animations must be recorded from the
running application, not drawn or reconstructed by the brand renderer.
PNG exports carry title, creator, source, copyright and rights fields, plus XMP.
SVG and WebP sources carry the corresponding ownership metadata. The manifest
records the generation prompt and provenance; generation does not establish
trademark clearance.

## Recording the real interface

The walkthrough browses a 48-variable store, builds selections, filters
`DATABASE` settings, edits `DATABASE_USER` from `app_reader` to `app_service`,
filters `FEATURE` flags, and returns to the full catalog. The keyboard selection
and text-entry cursors move in the actual application.

[demo-variables.json](demo-variables.json) contains the fictitious starting
dataset. All service domains use reserved `.test` names, and credential-shaped
values are explicitly nonfunctional placeholders. Always create a disposable
home directory and set `HOME`, `XDG_CONFIG_HOME`, and `XDG_STATE_HOME` for both
seeding and launching. Import only the fixture's named variables through
`envman import NAME... --apply`; do not import the operator's process environment.

Launch a separate WezTerm process with
`wezterm --config-file docs/assets/wezterm-demo.lua start --always-new-process`.
Pass the isolated demo environment to its child command. The
[demo configuration](wezterm-demo.lua) matches the artwork's deep ink, mineral
teal, pale mint, and yellow-green accents without changing the user's normal
WezTerm configuration. Agent-driven capture must use an isolated display or a
freshly verified built-in laptop display, never the operator's external screen.

Capture only that window. Preserve its pixels and encode the sequence as
lossless animated WebP, with a shared-palette GIF fallback. Frame holds may be
paced for readability; do not fabricate UI transitions, redraw text, reveal
credentials, or add a simulated pointer. The current exports contain 65 distinct
frames. The README prefers WebP, falls back to GIF, and uses the real PNG when
reduced motion is requested. Brand re-rendering packages these recordings but
does not recreate or overwrite them.


## GitHub social preview

The public repository was checked on 2026-10-19 after the social-preview upload.
Its Open Graph and Twitter card metadata both serve the new sculpted teal
artwork from `social-preview.png`. The live README still referenced the older
lime-tile wordmark at that check; the matching README hero requires publishing
the local repository changes.

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
