import { useEffect, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import './GraphView.css';

const API_BASE = `http://${window.location.hostname}:8080`;

interface GraphNode {
  id: string;
  label: string;
  type: 'character' | 'location' | 'rule';
  traits?: string[];
  is_player?: boolean;
  description?: string;
}

interface Props {
  storyId: string;
  onClose: () => void;
}

const NODE_COLORS: Record<string, string> = {
  character: '#e8c170',
  location: '#69db7c',
  rule: '#748ffc',
};

export default function GraphView({ storyId, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const resp = await fetch(`${API_BASE}/api/stories/${storyId}/graph`);
        const data = await resp.json();
        if (cancelled) return;

        const elements: cytoscape.ElementDefinition[] = [];

        for (const node of data.nodes || []) {
          elements.push({
            data: {
              id: node.id,
              label: node.label,
              type: node.type,
              ...node,
            },
          });
        }

        for (const edge of data.edges || []) {
          // 只添加两端节点都存在的边
          const nodeIds = new Set((data.nodes || []).map((n: GraphNode) => n.id));
          if (nodeIds.has(edge.source) && nodeIds.has(edge.target)) {
            elements.push({
              data: {
                source: edge.source,
                target: edge.target,
                label: edge.label,
                type: edge.type,
                ...edge,
              },
            });
          }
        }

        if (!containerRef.current || cancelled) return;

        const cy = cytoscape({
          container: containerRef.current,
          elements,
          style: [
            {
              selector: 'node',
              style: {
                'background-color': (ele: cytoscape.NodeSingular) =>
                  NODE_COLORS[ele.data('type')] || '#888',
                label: 'data(label)',
                color: '#e8e8e8',
                'font-size': '11px',
                'text-valign': 'bottom',
                'text-margin-y': 6,
                width: (ele: cytoscape.NodeSingular) =>
                  ele.data('is_player') ? 40 : ele.data('type') === 'character' ? 30 : 20,
                height: (ele: cytoscape.NodeSingular) =>
                  ele.data('is_player') ? 40 : ele.data('type') === 'character' ? 30 : 20,
                'border-width': (ele: cytoscape.NodeSingular) =>
                  ele.data('is_player') ? 3 : 0,
                'border-color': '#fff',
              } as cytoscape.Css.Node,
            },
            {
              selector: 'edge',
              style: {
                width: 1.5,
                'line-color': 'rgba(255,255,255,0.2)',
                'target-arrow-color': 'rgba(255,255,255,0.3)',
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
                label: 'data(label)',
                color: 'rgba(255,255,255,0.3)',
                'font-size': '9px',
                'text-rotation': 'autorotate',
              } as cytoscape.Css.Edge,
            },
            {
              selector: ':selected',
              style: {
                'border-width': 3,
                'border-color': '#e8c170',
              },
            },
          ],
          layout: {
            name: 'cose',
            animate: true,
            animationDuration: 500,
            nodeRepulsion: () => 8000,
            idealEdgeLength: () => 120,
            gravity: 0.3,
          } as cytoscape.CoseLayoutOptions,
        });

        cy.on('tap', 'node', (e) => {
          setSelected(e.target.data());
        });

        cy.on('tap', 'edge', (e) => {
          setSelected(e.target.data());
        });

        cy.on('tap', (e) => {
          if (e.target === cy) setSelected(null);
        });

        cyRef.current = cy;
        setLoading(false);
      } catch (err) {
        console.error('图加载失败:', err);
        setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
      cyRef.current?.destroy();
    };
  }, [storyId]);

  return (
    <div className="graph-view">
      <div className="graph-view__header">
        <h3>世界关系图</h3>
        <div className="graph-view__legend">
          <span className="graph-legend" style={{ color: NODE_COLORS.character }}>● 角色</span>
          <span className="graph-legend" style={{ color: NODE_COLORS.location }}>● 地点</span>
          <span className="graph-legend" style={{ color: NODE_COLORS.rule }}>● 规则</span>
        </div>
        <button className="graph-view__close" onClick={onClose}>✕</button>
      </div>

      <div className="graph-view__container" ref={containerRef}>
        {loading && <div className="graph-view__loading">加载图数据...</div>}
      </div>

      {selected && (
        <div className="graph-view__detail">
          {/* 头部：名称 + 立绘 */}
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            {selected.sprite ? (
              <img
                src={`${API_BASE}${String(selected.sprite)}`}
                alt=""
                style={{ width: 60, height: 80, objectFit: 'cover', borderRadius: 4, background: 'rgba(0,0,0,0.3)' }}
              />
            ) : null}
            <div>
              <strong>{String(selected.label || '(unnamed)')}</strong>
            </div>
          </div>

          {Object.entries(selected).map(([key, value]: [string, unknown]) => {
            if (['id', 'label', 'source', 'target', 'sprite', 'card_preview'].includes(key)) return null;
            if (value === undefined || value === null || value === '' || value === false) return null;
            const display = Array.isArray(value) ? value.join(', ') : String(value);
            if (!display || display === '0') return null;
            const labels: Record<string, string> = {
              type: '类型', traits: '性格', speech_style: '说话风格', appearance: '外貌',
              identity: '身份', is_player: '玩家', card_version: '版本', description: '描述',
              category: '分类',
            };
            return (
              <div key={key} className="graph-detail__field">
                <span className="graph-detail__field-key">{labels[key] || key}</span>
                <span className="graph-detail__field-val">{String(display)}</span>
              </div>
            );
          })}

          {(() => {
            const preview = String(selected.card_preview || '');
            if (!preview) return null;
            return (
              <div className="graph-detail__section">
                <div className="graph-detail__section-title">角色卡</div>
                <div className="graph-detail__card">{preview}</div>
              </div>
            );
          })()}

          {selected.source ? (
            <div className="graph-detail__section">
              <div className="graph-detail__section-title">连接</div>
              <div className="graph-detail__field">
                <span className="graph-detail__field-key">从</span>
                <span className="graph-detail__field-val">{String(selected.source)}</span>
              </div>
              <div className="graph-detail__field">
                <span className="graph-detail__field-key">到</span>
                <span className="graph-detail__field-val">{String(selected.target)}</span>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
