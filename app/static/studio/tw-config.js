// Merged from design/stitch #1 and #3 inline tailwind.config (#3 wins on shared keys).
// Fonts use the system Korean font stack (no web font download).
tailwind.config = {
  "darkMode": "class",
  "theme": {
    "extend": {
      "colors": {
        "surface-container-low": "#fdf1ec",
        "primary-fixed-dim": "#ffb4a4",
        "on-primary-fixed": "#3e0500",
        "surface": "#fff8f5",
        "surface-container": "#f7ebe6",
        "outline": "#8c716b",
        "secondary": "#8e4e14",
        "primary": "#d95338",
        "inverse-surface": "#352f2c",
        "tertiary-fixed": "#ece0d9",
        "inverse-primary": "#ffb4a4",
        "secondary-fixed-dim": "#ffb780",
        "on-secondary-container": "#783d01",
        "on-tertiary-fixed-variant": "#4d4540",
        "on-surface-variant": "#59413c",
        "on-error-container": "#93000a",
        "on-primary": "#ffffff",
        "on-secondary-fixed": "#2f1400",
        "inverse-on-surface": "#faeee9",
        "on-primary-fixed-variant": "#8b1b05",
        "on-tertiary": "#ffffff",
        "primary-fixed": "#ffdad3",
        "error": "#ba1a1a",
        "on-secondary": "#ffffff",
        "on-error": "#ffffff",
        "on-secondary-fixed-variant": "#6f3800",
        "surface-tint": "#ac331b",
        "on-primary-container": "#fffbff",
        "surface-variant": "#ece0db",
        "on-background": "#201a18",
        "surface-container-high": "#f2e6e1",
        "surface-container-lowest": "#ffffff",
        "on-tertiary-fixed": "#201a16",
        "secondary-fixed": "#ffdcc4",
        "error-container": "#ffdad6",
        "tertiary": "#635a55",
        "outline-variant": "#e0bfb8",
        "tertiary-fixed-dim": "#d0c4be",
        "surface-dim": "#e3d8d3",
        "on-tertiary-container": "#fffbff",
        "primary-container": "#cb492f",
        "tertiary-container": "#7c736d",
        "secondary-container": "#ffab69",
        "on-surface": "#201a18",
        "surface-bright": "#fff8f5",
        "background": "#fff8f5",
        "surface-container-highest": "#ece0db",
        "primary-dark": "#b83d25"
      },
      "borderRadius": {
        "DEFAULT": "0.25rem",
        "lg": "0.5rem",
        "xl": "0.75rem",
        "full": "9999px"
      },
      "spacing": {
        "space-sm": "0.5rem",
        "space-xs": "0.25rem",
        "margin": "2rem",
        "space-lg": "1.5rem",
        "gutter-mobile": "0.75rem",
        "space-xl": "2.25rem",
        "space-md": "1rem",
        "margin-mobile": "1rem",
        "gutter": "1.25rem"
      },
      "fontFamily": {
        "sans": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "body-md": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "headline-md": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "label-md": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "body-sm": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "code-sm": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "headline-sm": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "headline-xl": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "label-sm": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "body-lg": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "headline-lg-mobile": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "headline-xl-mobile": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ],
        "headline-lg": [
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "Malgun Gothic",
          "system-ui",
          "sans-serif"
        ]
      },
      "fontSize": {
        "body-md": [
          "14px",
          {
            "lineHeight": "22px",
            "letterSpacing": "-0.005em",
            "fontWeight": "400"
          }
        ],
        "headline-md": [
          "20px",
          {
            "lineHeight": "28px",
            "letterSpacing": "-0.01em",
            "fontWeight": "600"
          }
        ],
        "label-md": [
          "12px",
          {
            "lineHeight": "16px",
            "letterSpacing": "0.02em",
            "fontWeight": "600"
          }
        ],
        "body-sm": [
          "13px",
          {
            "lineHeight": "20px",
            "letterSpacing": "0em",
            "fontWeight": "400"
          }
        ],
        "code-sm": [
          "12px",
          {
            "lineHeight": "18px",
            "letterSpacing": "0em",
            "fontWeight": "500"
          }
        ],
        "headline-sm": [
          "16px",
          {
            "lineHeight": "24px",
            "letterSpacing": "-0.005em",
            "fontWeight": "600"
          }
        ],
        "headline-xl": [
          "36px",
          {
            "lineHeight": "44px",
            "letterSpacing": "-0.02em",
            "fontWeight": "700"
          }
        ],
        "label-sm": [
          "11px",
          {
            "lineHeight": "14px",
            "letterSpacing": "0.03em",
            "fontWeight": "600"
          }
        ],
        "body-lg": [
          "16px",
          {
            "lineHeight": "26px",
            "letterSpacing": "-0.01em",
            "fontWeight": "400"
          }
        ],
        "headline-lg-mobile": [
          "22px",
          {
            "lineHeight": "30px",
            "letterSpacing": "-0.01em",
            "fontWeight": "600"
          }
        ],
        "headline-xl-mobile": [
          "28px",
          {
            "lineHeight": "36px",
            "letterSpacing": "-0.01em",
            "fontWeight": "700"
          }
        ],
        "headline-lg": [
          "28px",
          {
            "lineHeight": "36px",
            "letterSpacing": "-0.015em",
            "fontWeight": "600"
          }
        ]
      }
    }
  }
};
