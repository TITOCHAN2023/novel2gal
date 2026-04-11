import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// 去掉 StrictMode 避免双渲染干扰调试
createRoot(document.getElementById('root')!).render(<App />)
