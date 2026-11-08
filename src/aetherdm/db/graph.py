"""NetworkX graph helpers for the location graph."""

import networkx as nx

from aetherdm.models import Connection, LocationNode


def build_graph(locations: list[LocationNode]) -> nx.DiGraph:
    """Build a NetworkX directed graph from location nodes and their connections."""
    g = nx.DiGraph()
    for loc in locations:
        g.add_node(
            loc.id,
            name=loc.name,
            description=loc.description,
            tags=loc.tags,
            environment=loc.environment.model_dump(),
            characters=loc.characters,
        )
        for conn in loc.connections:
            g.add_edge(
                loc.id,
                conn.target_id,
                type=conn.type,
                travel_time=conn.travel_time,
                propagation_modifier=conn.propagation_modifier,
            )
    return g


def get_adjacent_ids(graph: nx.DiGraph, location_id: str) -> list[str]:
    """Get all location IDs directly connected to the given location."""
    return list(graph.neighbors(location_id))


def get_connection(graph: nx.DiGraph, from_id: str, to_id: str) -> dict | None:
    """Get connection data between two locations, or None if not connected."""
    if graph.has_edge(from_id, to_id):
        return dict(graph[from_id][to_id])
    return None


def locations_to_nodes(graph: nx.DiGraph) -> list[LocationNode]:
    """Reconstruct LocationNode objects from a NetworkX graph."""
    result = []
    for node_id, data in graph.nodes(data=True):
        connections = []
        for _, target_id, edge_data in graph.out_edges(node_id, data=True):
            connections.append(
                Connection(
                    target_id=target_id,
                    type=edge_data.get("type", "path"),
                    travel_time=edge_data.get("travel_time", 1),
                    propagation_modifier=edge_data.get("propagation_modifier", 1.0),
                )
            )
        env_data = data.get("environment", {})
        from aetherdm.models import Environment, LocationNode

        result.append(
            LocationNode(
                id=node_id,
                name=data.get("name", node_id),
                description=data.get("description", ""),
                tags=data.get("tags", []),
                environment=Environment(**env_data) if env_data else Environment(),
                connections=connections,
                characters=data.get("characters", []),
            )
        )
    return result
