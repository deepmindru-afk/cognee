import os
import json
import networkx

from cognee.shared.logging_utils import get_logger
from cognee.infrastructure.files.storage.LocalFileStorage import LocalFileStorage

logger = get_logger()


async def cognee_network_visualization(graph_data, destination_file_path: str = None):
    nodes_data, edges_data = graph_data

    G = networkx.DiGraph()

    nodes_list = []
    color_map = {
        "Entity": "#f47710",
        "EntityType": "#6510f4",
        "DocumentChunk": "#801212",
        "TextSummary": "#1077f4",
        "TableRow": "#f47710",
        "TableType": "#6510f4",
        "ColumnValue": "#13613a",
        "default": "#D3D3D3",
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

    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script src="https://d3js.org/d3.v5.min.js"></script>
        <style>
            body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: linear-gradient(90deg, #101010, #1a1a2e); color: white; font-family: 'Inter', sans-serif; }

            svg { width: 100vw; height: 100vh; display: block; }
            .links line { stroke: rgba(255, 255, 255, 0.4); stroke-width: 2px; }
            .links line.weighted { stroke: rgba(255, 215, 0, 0.7); }
            .links line.multi-weighted { stroke: rgba(0, 255, 127, 0.8); }
            .nodes circle { stroke: white; stroke-width: 0.5px; filter: drop-shadow(0 0 5px rgba(255,255,255,0.3)); }
            .node-label { font-size: 5px; font-weight: bold; fill: white; text-anchor: middle; dominant-baseline: middle; font-family: 'Inter', sans-serif; pointer-events: none; }
            .edge-label { font-size: 3px; fill: rgba(255, 255, 255, 0.7); text-anchor: middle; dominant-baseline: middle; font-family: 'Inter', sans-serif; pointer-events: none; }
            
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
        </style>
    </head>
    <body>
        <svg></svg>
        <div class="tooltip" id="tooltip"></div>
        <script>
            var nodes = {nodes};
            var links = {links};

            var svg = d3.select("svg"),
                width = window.innerWidth,
                height = window.innerHeight;

            var container = svg.append("g");
            var tooltip = d3.select("#tooltip");

            var simulation = d3.forceSimulation(nodes)
                .force("link", d3.forceLink(links).id(d => d.id).strength(0.1))
                .force("charge", d3.forceManyBody().strength(-275))
                .force("center", d3.forceCenter(width / 2, height / 2))
                .force("x", d3.forceX().strength(0.1).x(width / 2))
                .force("y", d3.forceY().strength(0.1).y(height / 2));

            var link = container.append("g")
                .attr("class", "links")
                .selectAll("line")
                .data(links)
                .enter().append("line")
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

            var node = nodeGroup.append("circle")
                .attr("r", 13)
                .attr("fill", d => d.color)
                .call(d3.drag()
                    .on("start", dragstarted)
                    .on("drag", dragged)
                    .on("end", dragended));

            nodeGroup.append("text")
                .attr("class", "node-label")
                .attr("dy", 4)
                .attr("text-anchor", "middle")
                .text(d => d.name);

            node.append("title").text(d => JSON.stringify(d));

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
            });

            svg.call(d3.zoom().on("zoom", function() {
                container.attr("transform", d3.event.transform);
            }));

            function dragstarted(d) {
                if (!d3.event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
            }

            function dragged(d) {
                d.fx = d3.event.x;
                d.fy = d3.event.y;
            }

            function dragended(d) {
                if (!d3.event.active) simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
            }

            window.addEventListener("resize", function() {
                width = window.innerWidth;
                height = window.innerHeight;
                svg.attr("width", width).attr("height", height);
                simulation.force("center", d3.forceCenter(width / 2, height / 2));
                simulation.alpha(1).restart();
            });
        </script>

        <iframe
          src="https://btn.portalos.online/embed?theme=system"
          style="width: 320px; height: 64px;"
        ></iframe>
    </body>
    </html>
    """

    html_content = html_template.replace("{nodes}", json.dumps(nodes_list))
    html_content = html_content.replace("{links}", json.dumps(links_list))

    if not destination_file_path:
        home_dir = os.path.expanduser("~")
        destination_file_path = os.path.join(home_dir, "graph_visualization.html")

    dir_path = os.path.dirname(destination_file_path)
    file_path = os.path.basename(destination_file_path)

    file_storage = LocalFileStorage(dir_path)

    file_storage.store(file_path, html_content, overwrite=True)

    logger.info(f"Graph visualization saved as {destination_file_path}")

    return html_content
