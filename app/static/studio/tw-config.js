// Merged from design/stitch #1 and #3 inline tailwind.config (#3 wins on shared keys).
// Fonts use the system Korean font stack (no web font download).
// Color tokens are CSS variables (space-separated RGB) so a page can override them
// under html.dark (workspace.html does; studio.html keeps the light values).
(function () {
  var st = document.createElement("style");
  st.id = "tw-color-tokens";
  st.textContent = ":root{--c-surface-container-low:253 241 236; --c-primary-fixed-dim:255 180 164; --c-on-primary-fixed:62 5 0; --c-surface:255 248 245; --c-surface-container:247 235 230; --c-outline:140 113 107; --c-secondary:142 78 20; --c-primary:217 83 56; --c-inverse-surface:53 47 44; --c-tertiary-fixed:236 224 217; --c-inverse-primary:255 180 164; --c-secondary-fixed-dim:255 183 128; --c-on-secondary-container:120 61 1; --c-on-tertiary-fixed-variant:77 69 64; --c-on-surface-variant:89 65 60; --c-on-error-container:147 0 10; --c-on-primary:255 255 255; --c-on-secondary-fixed:47 20 0; --c-inverse-on-surface:250 238 233; --c-on-primary-fixed-variant:139 27 5; --c-on-tertiary:255 255 255; --c-primary-fixed:255 218 211; --c-error:186 26 26; --c-on-secondary:255 255 255; --c-on-error:255 255 255; --c-on-secondary-fixed-variant:111 56 0; --c-surface-tint:172 51 27; --c-on-primary-container:255 251 255; --c-surface-variant:236 224 219; --c-on-background:32 26 24; --c-surface-container-high:242 230 225; --c-surface-container-lowest:255 255 255; --c-on-tertiary-fixed:32 26 22; --c-secondary-fixed:255 220 196; --c-error-container:255 218 214; --c-tertiary:99 90 85; --c-outline-variant:224 191 184; --c-tertiary-fixed-dim:208 196 190; --c-surface-dim:227 216 211; --c-on-tertiary-container:255 251 255; --c-primary-container:203 73 47; --c-tertiary-container:124 115 109; --c-secondary-container:255 171 105; --c-on-surface:32 26 24; --c-surface-bright:255 248 245; --c-background:255 248 245; --c-surface-container-highest:236 224 219; --c-primary-dark:184 61 37;}";
  document.head.appendChild(st);
})();
tailwind.config = {
  "darkMode": "class",
  "theme": {
    "extend": {
      "colors": {
        "surface-container-low": "rgb(var(--c-surface-container-low) / <alpha-value>)",
        "primary-fixed-dim": "rgb(var(--c-primary-fixed-dim) / <alpha-value>)",
        "on-primary-fixed": "rgb(var(--c-on-primary-fixed) / <alpha-value>)",
        "surface": "rgb(var(--c-surface) / <alpha-value>)",
        "surface-container": "rgb(var(--c-surface-container) / <alpha-value>)",
        "outline": "rgb(var(--c-outline) / <alpha-value>)",
        "secondary": "rgb(var(--c-secondary) / <alpha-value>)",
        "primary": "rgb(var(--c-primary) / <alpha-value>)",
        "inverse-surface": "rgb(var(--c-inverse-surface) / <alpha-value>)",
        "tertiary-fixed": "rgb(var(--c-tertiary-fixed) / <alpha-value>)",
        "inverse-primary": "rgb(var(--c-inverse-primary) / <alpha-value>)",
        "secondary-fixed-dim": "rgb(var(--c-secondary-fixed-dim) / <alpha-value>)",
        "on-secondary-container": "rgb(var(--c-on-secondary-container) / <alpha-value>)",
        "on-tertiary-fixed-variant": "rgb(var(--c-on-tertiary-fixed-variant) / <alpha-value>)",
        "on-surface-variant": "rgb(var(--c-on-surface-variant) / <alpha-value>)",
        "on-error-container": "rgb(var(--c-on-error-container) / <alpha-value>)",
        "on-primary": "rgb(var(--c-on-primary) / <alpha-value>)",
        "on-secondary-fixed": "rgb(var(--c-on-secondary-fixed) / <alpha-value>)",
        "inverse-on-surface": "rgb(var(--c-inverse-on-surface) / <alpha-value>)",
        "on-primary-fixed-variant": "rgb(var(--c-on-primary-fixed-variant) / <alpha-value>)",
        "on-tertiary": "rgb(var(--c-on-tertiary) / <alpha-value>)",
        "primary-fixed": "rgb(var(--c-primary-fixed) / <alpha-value>)",
        "error": "rgb(var(--c-error) / <alpha-value>)",
        "on-secondary": "rgb(var(--c-on-secondary) / <alpha-value>)",
        "on-error": "rgb(var(--c-on-error) / <alpha-value>)",
        "on-secondary-fixed-variant": "rgb(var(--c-on-secondary-fixed-variant) / <alpha-value>)",
        "surface-tint": "rgb(var(--c-surface-tint) / <alpha-value>)",
        "on-primary-container": "rgb(var(--c-on-primary-container) / <alpha-value>)",
        "surface-variant": "rgb(var(--c-surface-variant) / <alpha-value>)",
        "on-background": "rgb(var(--c-on-background) / <alpha-value>)",
        "surface-container-high": "rgb(var(--c-surface-container-high) / <alpha-value>)",
        "surface-container-lowest": "rgb(var(--c-surface-container-lowest) / <alpha-value>)",
        "on-tertiary-fixed": "rgb(var(--c-on-tertiary-fixed) / <alpha-value>)",
        "secondary-fixed": "rgb(var(--c-secondary-fixed) / <alpha-value>)",
        "error-container": "rgb(var(--c-error-container) / <alpha-value>)",
        "tertiary": "rgb(var(--c-tertiary) / <alpha-value>)",
        "outline-variant": "rgb(var(--c-outline-variant) / <alpha-value>)",
        "tertiary-fixed-dim": "rgb(var(--c-tertiary-fixed-dim) / <alpha-value>)",
        "surface-dim": "rgb(var(--c-surface-dim) / <alpha-value>)",
        "on-tertiary-container": "rgb(var(--c-on-tertiary-container) / <alpha-value>)",
        "primary-container": "rgb(var(--c-primary-container) / <alpha-value>)",
        "tertiary-container": "rgb(var(--c-tertiary-container) / <alpha-value>)",
        "secondary-container": "rgb(var(--c-secondary-container) / <alpha-value>)",
        "on-surface": "rgb(var(--c-on-surface) / <alpha-value>)",
        "surface-bright": "rgb(var(--c-surface-bright) / <alpha-value>)",
        "background": "rgb(var(--c-background) / <alpha-value>)",
        "surface-container-highest": "rgb(var(--c-surface-container-highest) / <alpha-value>)",
        "primary-dark": "rgb(var(--c-primary-dark) / <alpha-value>)"
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
