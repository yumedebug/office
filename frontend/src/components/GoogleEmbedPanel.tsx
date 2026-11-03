import { useMemo, useState } from 'react';

type GoogleKind = 'document' | 'spreadsheet' | 'presentation';

interface GoogleEmbedPanelProps {
  onClose: () => void;
}

function googleEmbedUrl(raw: string): { kind: GoogleKind; url: string } | null {
  try {
    const parsed = new URL(raw.trim());
    if (parsed.protocol !== 'https:' || parsed.hostname !== 'docs.google.com') {
      return null;
    }
    const match = /^\/(document|spreadsheets|presentation)\/d\/([^/]+)/.exec(parsed.pathname);
    if (!match) {
      return null;
    }
    const kind = match[1] === 'document'
      ? 'document'
      : match[1] === 'spreadsheets'
        ? 'spreadsheet'
        : 'presentation';
    const base = `https://docs.google.com/${match[1]}/d/${match[2]}/edit`;
    return { kind, url: `${base}?rm=minimal&embedded=true` };
  } catch {
    return null;
  }
}

export default function GoogleEmbedPanel({ onClose }: GoogleEmbedPanelProps) {
  const [value, setValue] = useState('');
  const embed = useMemo(() => googleEmbedUrl(value), [value]);

  return (
    <div className="google-embed-overlay" role="dialog" aria-modal="true" aria-label="Google ファイル">
      <div className="google-embed-panel">
        <div className="google-embed-header">
          <div>
            <strong>Google ファイルを埋め込む</strong>
            <p>Google ドキュメント・スプレッドシート・スライドの共有 URL を入力してください。</p>
          </div>
          <button type="button" className="tb-button" onClick={onClose}>閉じる</button>
        </div>
        <div className="google-embed-form">
          <input
            type="url"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="https://docs.google.com/spreadsheets/d/..."
            aria-label="Google URL"
          />
          {embed ? <span className="badge">{embed.kind}</span> : null}
        </div>
        {embed ? (
          <iframe
            className="google-embed-frame"
            title="Google ファイル"
            src={embed.url}
            sandbox="allow-forms allow-modals allow-popups allow-presentation allow-same-origin allow-scripts"
            referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <div className="google-embed-empty">
            <p>docs.google.com の共有 URL を入力すると、埋め込み可能なプレビューを表示します。</p>
            <p>編集権限や iframe を拒否する設定のファイルは埋め込めません。その場合は下のリンクから公式画面で編集してください。</p>
          </div>
        )}
        {embed ? (
          <div className="google-embed-footer">
            <span>Google 側の変更は自動で Office ファイルへ変換されません。</span>
            <a href={value} target="_blank" rel="noreferrer">Google で開く</a>
          </div>
        ) : null}
      </div>
    </div>
  );
}
