import { useState } from 'react'
import { useI18n } from '../../shared/i18n/I18nProvider'

const excluded = /^(?:\.git|\.svn|\.hg|node_modules|dist|build|target|__pycache__|\.venv|\.cache|\.next|\.nasus|\.nasus-complete|\.bundle\.zip|\.ssh|\.aws|\.npmrc|\.pypirc|\.netrc|\.terraform|\.ds_store|credentials\.json|\.env.*|id_rsa.*|id_ed25519.*|.*\.(?:pem|key|p12|pfx))$/i

export function CodeDirectoryPicker({ disabled, onUpload }: { disabled: boolean; onUpload: (files: File[]) => void }) {
  const { t } = useI18n()
  const [selection, setSelection] = useState<File[]>([])
  const files: File[] = [], removed: File[] = []
  let bytes = 0
  for (const file of selection) {
    if (file.webkitRelativePath.split('/').some(part => excluded.test(part))) removed.push(file)
    else { files.push(file); bytes += file.size }
  }
  return <div className="directory-picker">
    <label className="build-upload-button">{t('Upload code directory')}
      <input type="file" multiple ref={el => { el?.setAttribute('webkitdirectory', '') }} disabled={disabled}
        data-testid="code-directory-input" onChange={e => { setSelection(Array.from(e.target.files ?? [])); e.target.value = '' }} />
    </label>
    {selection.length > 0 && <div aria-live="polite"><strong>{selection[0].webkitRelativePath.split('/')[0]}</strong>
      <p>{t('{count} files · {bytes} bytes · {excluded} excluded', { count: files.length, bytes, excluded: removed.length })}</p>
      {removed.length > 0 && <details><summary>{t('Excluded files')}</summary>
        <ul>{removed.map(file => <li key={file.webkitRelativePath}>{file.webkitRelativePath}</li>)}</ul></details>}
      <button type="button" disabled={disabled || !files.length} onClick={() => { onUpload(files); setSelection([]) }}>{t('Upload snapshot')}</button>
      <button type="button" onClick={() => setSelection([])}>{t('Cancel')}</button>
    </div>}
  </div>
}
