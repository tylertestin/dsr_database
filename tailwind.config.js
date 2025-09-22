// tailwind.config.js
module.exports = {
    content: [
      // Paths to all HTML files so Tailwind can tree-shake unused classes:
      "./templates/**/*.html",
      "./static/**/*.js",
    ],
    theme: {
      extend: {
        colors: {
          background: "#1C1E22",
          panel: "#2A2D34",
          accent: "#4B86FF",
          // Add more custom colors as needed
        },
      },
    },
    plugins: [],
  };
  