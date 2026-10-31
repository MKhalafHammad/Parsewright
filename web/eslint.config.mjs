import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// Log text and API data are only ever rendered as escaped text (web/CLAUDE.md).
const config = [
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      "react/no-danger": "error",
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "Never render HTML from data: log text is untrusted.",
        },
        {
          selector: "MemberExpression[property.name=/^(innerHTML|outerHTML|insertAdjacentHTML)$/]",
          message: "Never write HTML from data: log text is untrusted.",
        },
        {
          selector: "CallExpression[callee.object.name='document'][callee.property.name=/^write(ln)?$/]",
          message: "Never write HTML from data: log text is untrusted.",
        },
        {
          selector: "JSXAttribute[name.name='srcDoc']",
          message: "Never render HTML from data: log text is untrusted.",
        },
      ],
    },
  },
  { ignores: [".next/**", "node_modules/**", "playwright-report/**", "test-results/**"] },
];

export default config;
