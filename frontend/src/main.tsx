import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

const container = document.getElementById('root');

if (!container) {
  throw new Error('#root が見つかりません。index.html を確認してください。');
}

// StrictMode is intentionally not used: FortuneSheet mounts canvases and does
// not tolerate React's double mount in development.
createRoot(container).render(<App />);
