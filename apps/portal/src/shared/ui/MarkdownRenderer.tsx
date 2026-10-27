import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function MarkdownRenderer({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      components={{
        a: ({ children, href }) => {
          const external = Boolean(href && /^https?:\/\//i.test(href))
          return (
            <a href={href} rel={external ? 'noreferrer' : undefined} target={external ? '_blank' : undefined}>
              {children}
            </a>
          )
        },
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
