-- Copyright © 2026 Crux Experts LLC
-- https://www.cruxexperts.com/
-- Private asset. Property of Crux Experts LLC. Use, reproduction, modification,
-- distribution, or publication without prior written permission is prohibited.
-- Task-local visual demo configuration. Do not install over a user's theme.
return {
  enable_tab_bar = false,
  initial_cols = 110,
  initial_rows = 34,
  font_size = 15,
  window_decorations = "RESIZE",
  window_padding = { left = 24, right = 24, top = 20, bottom = 20 },
  colors = {
    foreground = "#b9cdd0",
    background = "#071b22",
    cursor_bg = "#e4f49b",
    cursor_fg = "#071b22",
    selection_bg = "#28515a",
    selection_fg = "#f0f3ed",
    ansi = {
      "#071b22", "#e6957a", "#a2c98c", "#e4c48b",
      "#5c8992", "#b6a3b7", "#8fbfb9", "#b9cdd0",
    },
    brights = {
      "#66868b", "#f0aa91", "#c4dfb0", "#e4f49b",
      "#8bb1b9", "#d4bfce", "#b8e5da", "#f0f3ed",
    },
  },
}
