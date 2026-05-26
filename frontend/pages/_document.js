import { Html, Head, Main, NextScript } from 'next/document'

export default function Document() {
  return (
    <Html>
      <Head>
        {/* Fonts are self-hosted via @fontsource packages (no Google CDN) */}
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  )
}
