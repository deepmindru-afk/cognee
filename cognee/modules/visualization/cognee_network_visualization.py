import os
import json

from cognee.shared.logging_utils import get_logger
from cognee.infrastructure.files.storage.LocalFileStorage import LocalFileStorage

logger = get_logger()


async def cognee_network_visualization(graph_data, destination_file_path: str = None):
    import networkx

    nodes_data, edges_data = graph_data

    G = networkx.DiGraph()

    nodes_list = []
    color_map = {
        "Entity": "#5C10F4",
        "EntityType": "#A550FF",
        "DocumentChunk": "#0DFF00",
        "TextSummary": "#5C10F4",
        "TableRow": "#A550FF",
        "TableType": "#5C10F4",
        "ColumnValue": "#757470",
        "SchemaTable": "#A550FF",
        "DatabaseSchema": "#5C10F4",
        "SchemaRelationship": "#323332",
        "default": "#D8D8D8",
    }

    for node_id, node_info in nodes_data:
        node_info = node_info.copy()
        node_info["id"] = str(node_id)
        node_info["color"] = color_map.get(node_info.get("type", "default"), "#D3D3D3")
        node_info["name"] = node_info.get("name", str(node_id))

        try:
            del node_info[
                "updated_at"
            ]  #:TODO: We should decide what properties to show on the nodes and edges, we dont necessarily need all.
        except KeyError:
            pass

        try:
            del node_info["created_at"]
        except KeyError:
            pass

        nodes_list.append(node_info)
        G.add_node(node_id, **node_info)

    edge_labels = {}
    links_list = []
    for source, target, relation, edge_info in edges_data:
        source = str(source)
        target = str(target)
        G.add_edge(source, target)
        edge_labels[(source, target)] = relation

        # Extract edge metadata including all weights
        all_weights = {}
        primary_weight = None

        if edge_info:
            # Single weight (backward compatibility)
            if "weight" in edge_info:
                all_weights["default"] = edge_info["weight"]
                primary_weight = edge_info["weight"]

            # Multiple weights
            if "weights" in edge_info and isinstance(edge_info["weights"], dict):
                all_weights.update(edge_info["weights"])
                # Use the first weight as primary for visual thickness if no default weight
                if primary_weight is None and edge_info["weights"]:
                    primary_weight = next(iter(edge_info["weights"].values()))

            # Individual weight fields (weight_strength, weight_confidence, etc.)
            for key, value in edge_info.items():
                if key.startswith("weight_") and isinstance(value, (int, float)):
                    weight_name = key[7:]  # Remove "weight_" prefix
                    all_weights[weight_name] = value

        link_data = {
            "source": source,
            "target": target,
            "relation": relation,
            "weight": primary_weight,  # Primary weight for backward compatibility
            "all_weights": all_weights,  # All weights for display
            "relationship_type": edge_info.get("relationship_type") if edge_info else None,
            "edge_info": edge_info if edge_info else {},
        }
        links_list.append(link_data)

    html_template = r"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script src="https://d3js.org/d3.v5.min.js"></script>
        <script src="https://d3js.org/d3-contour.v1.min.js"></script>
        <style>
            body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: linear-gradient(90deg, #101010, #1a1a2e); color: white; font-family: 'Inter', sans-serif; }

            svg { width: 100vw; height: 100vh; display: block; }
            .links line { stroke: rgba(160, 160, 160, 0.25); stroke-width: 1.5px; stroke-linecap: round; }
            .links line.weighted { stroke: rgba(255, 215, 0, 0.4); }
            .links line.multi-weighted { stroke: rgba(0, 255, 127, 0.45); }
            .nodes circle { stroke: white; stroke-width: 0.5px; }
            .node-label { font-size: 5px; font-weight: bold; fill: #F4F4F4; text-anchor: middle; dominant-baseline: middle; font-family: 'Inter', sans-serif; pointer-events: none; }
            .edge-label { font-size: 3px; fill: #F4F4F4; text-anchor: middle; dominant-baseline: middle; font-family: 'Inter', sans-serif; pointer-events: none; paint-order: stroke; stroke: rgba(50,51,50,0.75); stroke-width: 1px; }

            .density path { mix-blend-mode: screen; }

            .tooltip {
                position: absolute;
                text-align: left;
                padding: 8px;
                font-size: 12px;
                background: rgba(0, 0, 0, 0.9);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 4px;
                pointer-events: none;
                opacity: 0;
                transition: opacity 0.2s;
                z-index: 1000;
                max-width: 300px;
                word-wrap: break-word;
            }
            #info-panel {
                position: fixed;
                left: 12px;
                top: 12px;
                width: 340px;
                max-height: calc(100vh - 24px);
                overflow: auto;
                background: rgba(50, 51, 50, 0.7);
                backdrop-filter: blur(6px);
                border: 1px solid rgba(216, 216, 216, 0.35);
                border-radius: 8px;
                color: #F4F4F4;
                padding: 12px 14px;
                z-index: 1100;
            }
            #info-panel h3 { margin: 0 0 8px 0; font-size: 14px; color: #F4F4F4; }
            #info-panel .kv { font-size: 12px; line-height: 1.4; }
            #info-panel .kv .k { color: #D8D8D8; }
            #info-panel .kv .v { color: #F4F4F4; }
            #info-panel .placeholder { opacity: 0.7; font-size: 12px; }
        </style>
    </head>
    <body>
        <svg></svg>
        <div class="tooltip" id="tooltip"></div>
        <div id="info-panel"><div class="placeholder">Hover a node or edge to inspect details</div></div>
        <script>
            var nodes = {nodes};
            var links = {links};

            var svg = d3.select("svg"),
                width = window.innerWidth,
                height = window.innerHeight;

            var container = svg.append("g");
            var tooltip = d3.select("#tooltip");
            var infoPanel = d3.select('#info-panel');

            function renderInfo(title, entries){
                function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
                var html = '<h3>' + esc(title) + '</h3>';
                html += '<div class="kv">';
                entries.forEach(function(e){
                    html += '<div><span class="k">' + esc(e.k) + ':</span> <span class="v">' + esc(e.v) + '</span></div>';
                });
                html += '</div>';
                infoPanel.html(html);
            }
            function pickDescription(obj){
                if (!obj) return null;
                var keys = ['description','summary','text','content'];
                for (var i=0; i<keys.length; i++){
                    var v = obj[keys[i]];
                    if (typeof v === 'string' && v.trim()) return v.trim();
                }
                return null;
            }
            function truncate(s, n){ if (!s) return s; return s.length > n ? (s.slice(0, n) + '…') : s; }
            function renderNodeInfo(n){
                var entries = [];
                if (n.name) entries.push({k:'Name', v: n.name});
                if (n.type) entries.push({k:'Type', v: n.type});
                if (n.id) entries.push({k:'ID', v: n.id});
                var desc = pickDescription(n) || pickDescription(n.properties);
                if (desc) entries.push({k:'Description', v: truncate(desc.replace(/\s+/g,' ').trim(), 280)});
                if (n.properties) {
                    Object.keys(n.properties).slice(0, 12).forEach(function(key){
                        var v = n.properties[key];
                        if (v !== undefined && v !== null && typeof v !== 'object') entries.push({k: key, v: String(v)});
                    });
                }
                renderInfo(n.name || 'Node', entries);
            }
            function renderEdgeInfo(e){
                var entries = [];
                if (e.relation) entries.push({k:'Relation', v: e.relation});
                if (e.weight !== undefined && e.weight !== null) entries.push({k:'Weight', v: e.weight});
                if (e.all_weights && Object.keys(e.all_weights).length){
                    Object.keys(e.all_weights).slice(0, 8).forEach(function(k){ entries.push({k: 'w.'+k, v: e.all_weights[k]}); });
                }
                if (e.relationship_type) entries.push({k:'Type', v: e.relationship_type});
                var edesc = pickDescription(e.edge_info);
                if (edesc) entries.push({k:'Description', v: truncate(edesc.replace(/\s+/g,' ').trim(), 280)});
                renderInfo('Edge', entries);
            }

            // Basic runtime diagnostics
            console.log('[Cognee Visualization] nodes:', nodes ? nodes.length : 0, 'links:', links ? links.length : 0);
            window.addEventListener('error', function(e){
                try {
                    tooltip.html('<strong>Error:</strong> ' + e.message)
                        .style('left', '12px')
                        .style('top', '12px')
                        .style('opacity', 1);
                } catch(_) {}
            });

            // Normalize node IDs and link endpoints for robustness
            function resolveId(d){ return (d && (d.id || d.node_id || d.uuid || d.external_id || d.name)) || undefined; }
            if (Array.isArray(nodes)) {
                nodes.forEach(function(n){ var id = resolveId(n); if (id !== undefined) n.id = id; });
            }
            if (Array.isArray(links)) {
                links.forEach(function(l){
                    if (typeof l.source === 'object') l.source = resolveId(l.source);
                    if (typeof l.target === 'object') l.target = resolveId(l.target);
                });
            }

            if (!nodes || nodes.length === 0) {
                container.append('text')
                    .attr('x', width / 2)
                    .attr('y', height / 2)
                    .attr('fill', '#fff')
                    .attr('font-size', 14)
                    .attr('text-anchor', 'middle')
                    .text('No graph data available');
            }

            // Visual defs - reusable glow
            var defs = svg.append("defs");
            var glow = defs.append("filter").attr("id", "glow")
                .attr("x", "-30%")
                .attr("y", "-30%")
                .attr("width", "160%")
                .attr("height", "160%");
            glow.append("feGaussianBlur").attr("stdDeviation", 8).attr("result", "coloredBlur");
            var feMerge = glow.append("feMerge");
            feMerge.append("feMergeNode").attr("in", "coloredBlur");
            feMerge.append("feMergeNode").attr("in", "SourceGraphic");

            // Stronger glow for hovered adjacency
            var glowStrong = defs.append("filter").attr("id", "glow-strong")
                .attr("x", "-40%")
                .attr("y", "-40%")
                .attr("width", "180%")
                .attr("height", "180%");
            glowStrong.append("feGaussianBlur").attr("stdDeviation", 14).attr("result", "coloredBlur");
            var feMerge2 = glowStrong.append("feMerge");
            feMerge2.append("feMergeNode").attr("in", "coloredBlur");
            feMerge2.append("feMergeNode").attr("in", "SourceGraphic");

            var currentTransform = d3.zoomIdentity;
            var densityZoomTimer = null;
            var isInteracting = false;
            var labelBaseSize = 10;
            function getGroupKey(d){ return d && (d.type || d.category || d.group || d.color) || 'default'; }

            var simulation = d3.forceSimulation(nodes)
                .force("link", d3.forceLink(links).id(function(d){ return d.id; }).distance(100).strength(0.2))
                .force("charge", d3.forceManyBody().strength(-180))
                .force("collide", d3.forceCollide().radius(16).iterations(2))
                .force("center", d3.forceCenter(width / 2, height / 2))
                .force("x", d3.forceX().strength(0.06).x(width / 2))
                .force("y", d3.forceY().strength(0.06).y(height / 2))
                .alphaDecay(0.06)
                .velocityDecay(0.6);

            // Density layer (sibling of container to avoid double transforms)
            var densityLayer = svg.append("g")
                .attr("class", "density")
                .style("pointer-events", "none");
            if (densityLayer.lower) densityLayer.lower();

            var link = container.append("g")
                .attr("class", "links")
                .selectAll("line")
                .data(links)
                .enter().append("line")
                .style("opacity", 0)
                .style("pointer-events", "none")
                .attr("stroke-width", d => {
                    if (d.weight) return Math.max(2, d.weight * 5);
                    if (d.all_weights && Object.keys(d.all_weights).length > 0) {
                        var avgWeight = Object.values(d.all_weights).reduce((a, b) => a + b, 0) / Object.values(d.all_weights).length;
                        return Math.max(2, avgWeight * 5);
                    }
                    return 2;
                })
                .attr("class", d => {
                    if (d.all_weights && Object.keys(d.all_weights).length > 1) return "multi-weighted";
                    if (d.weight || (d.all_weights && Object.keys(d.all_weights).length > 0)) return "weighted";
                    return "";
                })
                .on("mouseover", function(d) {
                    // Create tooltip content for edge
                    renderEdgeInfo(d);
                    var content = "<strong>Edge Information</strong><br/>";
                    content += "Relationship: " + d.relation + "<br/>";

                    // Show all weights
                    if (d.all_weights && Object.keys(d.all_weights).length > 0) {
                        content += "<strong>Weights:</strong><br/>";
                        Object.keys(d.all_weights).forEach(function(weightName) {
                            content += "&nbsp;&nbsp;" + weightName + ": " + d.all_weights[weightName] + "<br/>";
                        });
                    } else if (d.weight !== null && d.weight !== undefined) {
                        content += "Weight: " + d.weight + "<br/>";
                    }

                    if (d.relationship_type) {
                        content += "Type: " + d.relationship_type + "<br/>";
                    }

                    // Add other edge properties
                    if (d.edge_info) {
                        Object.keys(d.edge_info).forEach(function(key) {
                            if (key !== 'weight' && key !== 'weights' && key !== 'relationship_type' &&
                                key !== 'source_node_id' && key !== 'target_node_id' &&
                                key !== 'relationship_name' && key !== 'updated_at' &&
                                !key.startsWith('weight_')) {
                                content += key + ": " + d.edge_info[key] + "<br/>";
                            }
                        });
                    }

                    tooltip.html(content)
                        .style("left", (d3.event.pageX + 10) + "px")
                        .style("top", (d3.event.pageY - 10) + "px")
                        .style("opacity", 1);
                })
                .on("mouseout", function(d) {
                    tooltip.style("opacity", 0);
                });

            var edgeLabels = container.append("g")
                .attr("class", "edge-labels")
                .selectAll("text")
                .data(links)
                .enter().append("text")
                .attr("class", "edge-label")
                .style("opacity", 0)
                .text(d => {
                    var label = d.relation;
                    if (d.all_weights && Object.keys(d.all_weights).length > 1) {
                        // Show count of weights for multiple weights
                        label += " (" + Object.keys(d.all_weights).length + " weights)";
                    } else if (d.weight) {
                        label += " (" + d.weight + ")";
                    } else if (d.all_weights && Object.keys(d.all_weights).length === 1) {
                        var singleWeight = Object.values(d.all_weights)[0];
                        label += " (" + singleWeight + ")";
                    }
                    return label;
                });

            var nodeGroup = container.append("g")
                .attr("class", "nodes")
                .selectAll("g")
                .data(nodes)
                .enter().append("g");

            // Color fallback by type when d.color is missing
            var colorByType = {
                "Entity": "#5C10F4",
                "EntityType": "#A550FF",
                "DocumentChunk": "#0DFF00",
                "TextSummary": "#5C10F4",
                "TableRow": "#A550FF",
                "TableType": "#5C10F4",
                "ColumnValue": "#757470",
                "SchemaTable": "#A550FF",
                "DatabaseSchema": "#5C10F4",
                "SchemaRelationship": "#323332"
            };

            var node = nodeGroup.append("circle")
                .attr("r", 13)
                .attr("fill", function(d){ return d.color || colorByType[d.type] || "#D3D3D3"; })
                .style("filter", "url(#glow)")
                .attr("shape-rendering", "geometricPrecision")
                .call(d3.drag()
                    .on("start", dragstarted)
                    .on("drag", function(d){ dragged(d); updateDensity(); showAdjacency(d); })
                    .on("end", dragended));

            // Show links only for hovered node adjacency
            function isAdjacent(linkDatum, nodeId) {
                var sid = linkDatum && linkDatum.source && (linkDatum.source.id || linkDatum.source);
                var tid = linkDatum && linkDatum.target && (linkDatum.target.id || linkDatum.target);
                return sid === nodeId || tid === nodeId;
            }

            function showAdjacency(d) {
                var nodeId = d && (d.id || d.node_id || d.uuid || d.external_id || d.name);
                if (!nodeId) return;
                // Build neighbor set
                var neighborIds = {};
                neighborIds[nodeId] = true;
                for (var i = 0; i < links.length; i++) {
                    var l = links[i];
                    var sid = l && l.source && (l.source.id || l.source);
                    var tid = l && l.target && (l.target.id || l.target);
                    if (sid === nodeId) neighborIds[tid] = true;
                    if (tid === nodeId) neighborIds[sid] = true;
                }

                link
                    .style("opacity", function(l){ return isAdjacent(l, nodeId) ? 0.95 : 0; })
                    .style("stroke", function(l){ return isAdjacent(l, nodeId) ? "rgba(255,255,255,0.95)" : null; })
                    .style("stroke-width", function(l){ return isAdjacent(l, nodeId) ? 2.5 : 1.5; });
                edgeLabels.style("opacity", function(l){ return isAdjacent(l, nodeId) ? 1 : 0; });
                densityLayer.style("opacity", 0.35);

                // Highlight neighbor nodes and dim others
                node
                    .style("opacity", function(n){ return neighborIds[n.id] ? 1 : 0.25; })
                    .style("filter", function(n){ return neighborIds[n.id] ? "url(#glow-strong)" : "url(#glow)"; })
                    .attr("r", function(n){ return neighborIds[n.id] ? 15 : 13; });
                // Raise highlighted nodes
                node.filter(function(n){ return neighborIds[n.id]; }).raise();
                // Neighbor labels brighter
                nodeGroup.select("text")
                    .style("opacity", function(n){ return neighborIds[n.id] ? 1 : 0.2; })
                    .style("font-size", function(n){
                        var size = neighborIds[n.id] ? Math.min(22, labelBaseSize * 1.25) : labelBaseSize;
                        return size + "px";
                    });
            }

            function clearAdjacency() {
                link.style("opacity", 0)
                    .style("stroke", null)
                    .style("stroke-width", 1.5);
                edgeLabels.style("opacity", 0);
                densityLayer.style("opacity", 1);
                node
                    .style("opacity", 1)
                    .style("filter", "url(#glow)")
                    .attr("r", 13);
                nodeGroup.select("text")
                    .style("opacity", 1)
                    .style("font-size", labelBaseSize + "px");
            }

            node.on("mouseover", function(d){ showAdjacency(d); })
                .on("mouseout", function(){ clearAdjacency(); });
            node.on("mouseover", function(d){ renderNodeInfo(d); tooltip.style('opacity', 0); });
            // Also bind on the group so labels trigger adjacency too
            nodeGroup.on("mouseover", function(d){ showAdjacency(d); })
                .on("mouseout", function(){ clearAdjacency(); });

            // Density always on; no hover gating

            // Add labels sparsely to reduce clutter (every ~50th node), and truncate long text
            nodeGroup
                .filter(function(d, i){ return i % 14 === 0; })
                .append("text")
                .attr("class", "node-label")
                .attr("dy", 4)
                .attr("text-anchor", "middle")
                .text(function(d){
                    var s = d && d.name ? String(d.name) : '';
                    return s.length > 40 ? (s.slice(0, 40) + "…") : s;
                })
                .style("font-size", labelBaseSize + "px");

            function applyLabelSize() {
                var k = (currentTransform && currentTransform.k) || 1;
                // Keep labels readable across zoom levels and hide when too small
                labelBaseSize = Math.max(7, Math.min(18, 10 / Math.sqrt(k)));
                nodeGroup.select("text")
                    .style("font-size", labelBaseSize + "px")
                    .style("display", (k < 0.35 ? "none" : null));
            }



            // Density cloud computation (throttled)
            var densityTick = 0;
            var geoPath = d3.geoPath().projection(null);
            var MAX_POINTS_PER_GROUP = 400;
            function updateDensity() {
                try {
                    if (isInteracting) return; // skip during interaction for smoother UX
                    if (typeof d3 === 'undefined' || typeof d3.contourDensity !== 'function') {
                        return; // d3-contour not available; skip gracefully
                    }
                    if (!nodes || nodes.length === 0) return;
                    var usable = nodes.filter(function(d){ return d && typeof d.x === 'number' && isFinite(d.x) && typeof d.y === 'number' && isFinite(d.y); });
                    if (usable.length < 3) return; // not enough positioned points yet

                    var t = currentTransform || d3.zoomIdentity;
                    if (t.k && t.k < 0.08) {
                        // Skip density at extreme zoom-out to avoid numerical instability/perf issues
                        densityLayer.selectAll('*').remove();
                        return;
                    }

                    function hexToRgb(hex){
                        if (!hex) return {r: 0, g: 200, b: 255};
                        var c = hex.replace('#','');
                        if (c.length === 3) c = c.split('').map(function(x){ return x+x; }).join('');
                        var num = parseInt(c, 16);
                        return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
                    }

                    // Build groups across all nodes
                    var groups = {};
                    for (var i = 0; i < usable.length; i++) {
                        var k = getGroupKey(usable[i]);
                        if (!groups[k]) groups[k] = [];
                        groups[k].push(usable[i]);
                    }

                    densityLayer.selectAll('*').remove();

                    Object.keys(groups).forEach(function(key){
                        var arr = groups[key];
                        if (!arr || arr.length < 3) return;

                        // Transform positions into screen space and sample to cap cost
                        var arrT = [];
                        var step = Math.max(1, Math.floor(arr.length / MAX_POINTS_PER_GROUP));
                        for (var j = 0; j < arr.length; j += step) {
                            var nx = t.applyX(arr[j].x);
                            var ny = t.applyY(arr[j].y);
                            if (isFinite(nx) && isFinite(ny)) {
                                arrT.push({ x: nx, y: ny, type: arr[j].type, color: arr[j].color });
                            }
                        }
                        if (arrT.length < 3) return;

                        // Compute adaptive bandwidth based on group spread
                        var cx = 0, cy = 0;
                        for (var k = 0; k < arrT.length; k++){ cx += arrT[k].x; cy += arrT[k].y; }
                        cx /= arrT.length; cy /= arrT.length;
                        var sumR = 0;
                        for (var k2 = 0; k2 < arrT.length; k2++){
                            var dx = arrT[k2].x - cx, dy = arrT[k2].y - cy;
                            sumR += Math.sqrt(dx*dx + dy*dy);
                        }
                        var avgR = sumR / arrT.length;
                        var dynamicBandwidth = Math.max(12, Math.min(80, avgR));
                        var densityBandwidth = dynamicBandwidth / (t.k || 1);

                        var contours = d3.contourDensity()
                            .x(function(d){ return d.x; })
                            .y(function(d){ return d.y; })
                            .size([width, height])
                            .bandwidth(densityBandwidth)
                            .thresholds(8)
                            (arrT);

                        if (!contours || contours.length === 0) return;
                        var maxVal = d3.max(contours, function(d){ return d.value; }) || 1;

                        // Use the first node color in the group or fallback neon palette
                        var baseColor = (arr.find(function(d){ return d && d.color; }) || {}).color || '#00c8ff';
                        var rgb = hexToRgb(baseColor);

                        var g = densityLayer.append('g').attr('data-group', key);
                        g.selectAll('path')
                            .data(contours)
                            .enter()
                            .append('path')
                            .attr('d', geoPath)
                            .attr('fill', 'rgb(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ')')
                            .attr('stroke', 'none')
                            .style('opacity', function(d){
                                var v = maxVal ? (d.value / maxVal) : 0;
                                var alpha = Math.pow(Math.max(0, Math.min(1, v)), 1.6); // accentuate clusters
                                return 0.65 * alpha; // up to 0.65 opacity at peak density
                            })
                            .style('filter', 'blur(2px)');
                    });
                } catch (e) {
                    // Reduce impact of any runtime errors during zoom
                    console.warn('Density update failed:', e);
                }
            }

            simulation.on("tick", function() {
                link.attr("x1", d => d.source.x)
                    .attr("y1", d => d.source.y)
                    .attr("x2", d => d.target.x)
                    .attr("y2", d => d.target.y);

                edgeLabels
                    .attr("x", d => (d.source.x + d.target.x) / 2)
                    .attr("y", d => (d.source.y + d.target.y) / 2 - 5);

                node.attr("cx", d => d.x)
                    .attr("cy", d => d.y);

                nodeGroup.select("text")
                    .attr("x", d => d.x)
                    .attr("y", d => d.y)
                    .attr("dy", 4)
                    .attr("text-anchor", "middle");

                densityTick += 1;
                if (densityTick % 24 === 0) updateDensity();
            });

            var zoomBehavior = d3.zoom()
                .on("start", function(){ isInteracting = true; densityLayer.style("opacity", 0.2); })
                .on("zoom", function(){
                    currentTransform = d3.event.transform;
                    container.attr("transform", currentTransform);
                })
                .on("end", function(){
                    if (densityZoomTimer) clearTimeout(densityZoomTimer);
                    densityZoomTimer = setTimeout(function(){ isInteracting = false; densityLayer.style("opacity", 1); updateDensity(); }, 140);
                });
            svg.call(zoomBehavior);

            function dragstarted(d) {
                if (!d3.event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
                isInteracting = true;
                densityLayer.style("opacity", 0.2);
            }

            function dragged(d) {
                d.fx = d3.event.x;
                d.fy = d3.event.y;
            }

            function dragended(d) {
                if (!d3.event.active) simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
                if (densityZoomTimer) clearTimeout(densityZoomTimer);
                densityZoomTimer = setTimeout(function(){ isInteracting = false; densityLayer.style("opacity", 1); updateDensity(); }, 140);
            }

            window.addEventListener("resize", function() {
                width = window.innerWidth;
                height = window.innerHeight;
                svg.attr("width", width).attr("height", height);
                simulation.force("center", d3.forceCenter(width / 2, height / 2));
                simulation.alpha(1).restart();
                updateDensity();
                applyLabelSize();
            });

            // Initial density draw
            updateDensity();
            applyLabelSize();
        </script>

    </body>
    </html>
    """

    # Safely embed JSON inside <script> by escaping </ to avoid prematurely closing the tag
    def _safe_json_embed(obj):
        return json.dumps(obj).replace("</", "<\\/")

    html_content = html_template.replace("{nodes}", _safe_json_embed(nodes_list))
    html_content = html_content.replace("{links}", _safe_json_embed(links_list))

    if not destination_file_path:
        home_dir = os.path.expanduser("~")
        destination_file_path = os.path.join(home_dir, "graph_visualization.html")

    dir_path = os.path.dirname(destination_file_path)
    file_path = os.path.basename(destination_file_path)

    file_storage = LocalFileStorage(dir_path)

    file_storage.store(file_path, html_content, overwrite=True)

    logger.info(f"Graph visualization saved as {destination_file_path}")

    return html_content
