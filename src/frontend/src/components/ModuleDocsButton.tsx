import { useState } from 'react'
import { Button, Drawer, Spin, Typography, message } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { SimpleMarkdown } from './SimpleMarkdown'

type Doc = {
  key: string
  title: string
  summary: string
  body: string
}

export function ModuleDocsButton({ docKey, label = 'Docs' }: { docKey: string; label?: string }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [doc, setDoc] = useState<Doc | null>(null)

  const load = async () => {
    setOpen(true)
    setLoading(true)
    try {
      const path =
        docKey === 'api_integration'
          ? '/api/access/docs/api/integration'
          : `/api/access/docs/${encodeURIComponent(docKey)}`
      const res = await api<Doc>(path)
      setDoc(res)
    } catch (e) {
      message.error(String(e))
      setOpen(false)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Button icon={<QuestionCircleOutlined />} onClick={() => void load()}>
        {label}
      </Button>
      <Drawer
        title={doc?.title || 'Documentation'}
        open={open}
        onClose={() => setOpen(false)}
        width={520}
      >
        {loading ? (
          <Spin />
        ) : doc ? (
          <div>
            <Typography.Paragraph type="secondary">{doc.summary}</Typography.Paragraph>
            <SimpleMarkdown text={doc.body} />
          </div>
        ) : null}
      </Drawer>
    </>
  )
}
