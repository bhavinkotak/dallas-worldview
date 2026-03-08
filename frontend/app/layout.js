import "./globals.css";

export const metadata = {
  title: "Dallas WorldView",
  description: "Dallas-focused geospatial command center",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
