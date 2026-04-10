# 游戏运行时引擎

## 结论：自研 Web 引擎

### 技术栈
- TypeScript + React
- 前后端分离架构

### 选型理由
- 项目本质是"动态展示 AI 生成内容"，传统 VN 引擎为预制脚本设计，方向不合
- Web 天然支持动态资产加载（fetch/async）
- API 集成无障碍（LLM、生图、TTS 都是 HTTP 请求）
- Gap 预生成机制适合 WebSocket/SSE 模式
- 跨平台：Web 原生，桌面端 Electron/Tauri

### VN 展示层核心循环
显示背景 → 显示立绘 → 显示对话 → 等待选择 → 循环

### 淘汰方案
- Ren'Py：Web 端无法发网络请求，动态加载需 hack
- Unity + Naninovel：2D VN 过于重量级
- Godot：VN 生态碎片化
- Monogatari.js：社区小，脚本导向

### 参考项目
- Endless Visual Novel (endlessvn.io) — 最接近的现有产品
- Pixi'VN — 可考虑作为底层减少样板代码

### 待定
- [ ] 是否引入 PixiJS / Pixi'VN 作为渲染层
- [ ] 前后端通信方案（REST / WebSocket / SSE）
- [ ] 桌面端打包方案（Electron vs Tauri）
