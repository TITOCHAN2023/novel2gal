import { useEffect, useRef, useState, useCallback } from 'react';
import cytoscape from 'cytoscape';
import './GraphView.css';

const API_BASE = '';

interface GraphNode {
  id: string;
  label: string;
  type: 'character' | 'location' | 'rule';
  traits?: string[];
  is_player?: boolean;
  description?: string;
  sprite?: string;
  card_preview?: string;
  [key: string]: unknown;
}

interface GraphEdge {
  source: string;
  target: string;
  label: string;
  type: string;
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
  // 全量数据缓存，用于渐进展开
  const allNodesRef = useRef<GraphNode[]>([]);
  const allEdgesRef = useRef<GraphEdge[]>([]);
  const expandedRef = useRef<Set<string>>(new Set());

  // 渐进展开：点击角色节点 → 显示其关联的边和邻居节点
  const expandNode = useCallback((nodeId: string) => {
    const cy = cyRef.current;
    if (!cy || expandedRef.current.has(nodeId)) return;
    expandedRef.current.add(nodeId);

    const nodeIds = new Set(cy.nodes().map((n) => n.id()));
    const newElements: cytoscape.ElementDefinition[] = [];

    // 找到与此节点关联的所有边
    for (const edge of allEdgesRef.current) {
      if (edge.source !== nodeId && edge.target !== nodeId) continue;
      // 添加边的另一端节点（如果还没显示）
      const otherId = edge.source === nodeId ? edge.target : edge.source;
      if (!nodeIds.has(otherId)) {
        const otherNode = allNodesRef.current.find((n) => n.id === otherId);
        if (otherNode) {
          newElements.push({ data: { ...otherNode } });
          nodeIds.add(otherId);
        }
      }
      // 添加边（如果两端都在图中）
      if (nodeIds.has(edge.source) && nodeIds.has(edge.target)) {
        const edgeId = `${edge.source}-${edge.target}-${edge.type}`;
        if (!cy.getElementById(edgeId).length) {
          newElements.push({ data: { id: edgeId, ...edge } });
        }
      }
    }

    if (newElements.length > 0) {
      cy.add(newElements);
      // 重新布局（只影响新节点）
      cy.layout({
        name: 'cose',
        animate: true,
        animationDuration: 300,
        nodeRepulsion: () => 6000,
        idealEdgeLength: () => 100,
        gravity: 0.3,
        fit: true,
      } as cytoscape.CoseLayoutOptions).run();
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const resp = await fetch(`${API_BASE}/api/stories/${storyId}/graph`);
        const data = await resp.json();
        if (cancelled) return;

        const nodes: GraphNode[] = data.nodes || [];
        const edges: GraphEdge[] = data.edges || [];
        allNodesRef.current = nodes;
        allEdgesRef.current = edges;
        expandedRef.current = new Set();

        // 初始只显示角色节点（不显示地点和规则，减少杂乱）
        const initialElements: cytoscape.ElementDefinition[] = [];
        const characterIds = new Set<string>();

        for (const node of nodes) {
          if (node.type === 'character') {
            initialElements.push({ data: { ...node } });
            characterIds.add(node.id);
          }
        }

        // 角色之间的直接关系边也显示
        for (const edge of edges) {
          if (characterIds.has(edge.source) && characterIds.has(edge.target)) {
            const edgeId = `${edge.source}-${edge.target}-${edge.type}`;
            initialElements.push({ data: { id: edgeId, ...edge } });
          }
        }

        if (!containerRef.current || cancelled) return;

        const cy = cytoscape({
          container: containerRef.current,
          elements: initialElements,
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
                  ele.data('is_player') ? 3 : expandedRef.current.has(ele.id()) ? 2 : 0,
                'border-color': (ele: cytoscape.NodeSingular) =>
                  ele.data('is_player') ? '#fff' : '#e8c170',
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

        // 双击角色节点 → 展开关联节点
        cy.on('dbltap', 'node', (e) => {
          expandNode(e.target.id());
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
  }, [storyId, expandNode]);

  return (
    <div className="graph-view">
      <div className="graph-view__header">
        <h3>世界关系图</h3>
        <div className="graph-view__legend">
          <span className="graph-legend" style={{ color: NODE_COLORS.character }}>● 角色</span>
          <span className="graph-legend" style={{ color: NODE_COLORS.location }}>● 地点</span>
          <span className="graph-legend" style={{ color: NODE_COLORS.rule }}>● 规则</span>
          <span className="graph-legend" style={{ color: 'rgba(255,255,255,0.4)', fontSize: 10 }}>双击角色展开关联</span>
        </div>
        <button className="graph-view__close" onClick={onClose}>&#10005;</button>
      </div>

      <div className="graph-view__container" ref={containerRef}>
        {loading && <div className="graph-view__loading">加载图数据...</div>}
      </div>

      {selected && (
        <div className="graph-view__detail">
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
            if (['id', 'label', 'source', 'target', 'sprite', 'card_preview', 'background'].includes(key)) return null;
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
