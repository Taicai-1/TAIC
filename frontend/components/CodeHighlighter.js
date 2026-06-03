import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/cjs/styles/prism';

export default function CodeHighlighter({ language, customStyle, children }) {
  return (
    <SyntaxHighlighter
      style={oneDark}
      language={language || 'text'}
      PreTag="div"
      customStyle={customStyle}
    >
      {children}
    </SyntaxHighlighter>
  );
}
