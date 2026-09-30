"""Project a locked C IDF's actual floor and wall coordinates for the household view."""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from joint_contract import require


LABELS = {"natural_1": "自然间 1", "natural_2": "自然间 2",
          "corridor": "过道", "kitchen": "厨房", "bathroom": "卫浴",
          "living_hall": "起居厅"}


def idf_objects(path):
    source = "\n".join(line.split("!", 1)[0] for line in Path(path).read_text().splitlines())
    for chunk in source.split(";"):
        parts = [part.strip() for part in chunk.split(",")]
        if parts and parts[0]:
            yield parts[0].lower(), parts


def vertices(parts, count_index):
    count = int(parts[count_index])
    require(3 <= count <= 20 and len(parts) >= count_index + 1 + count * 3,
            "Invalid C IDF surface vertices")
    return [tuple(float(value) for value in parts[count_index + 1 + i * 3:
                                                   count_index + 4 + i * 3])
            for i in range(count)]


def bottom_edge(points):
    lowest = min(point[2] for point in points)
    edge = list(dict.fromkeys((x, y) for x, y, z in points if abs(z - lowest) < 1e-5))
    return [list(point) for point in edge] if len(edge) == 2 else None


@lru_cache(maxsize=32)
def from_locked_idf(path, expected_sha, expected_area_m2):
    idf = Path(path)
    require(idf.is_file() and sha256(idf.read_bytes()).hexdigest() == expected_sha,
            "C IDF geometry source hash mismatch")
    floors, walls, openings = [], [], []
    zone_names = set()
    relative_geometry = False
    area = 0.0
    for kind, parts in idf_objects(idf):
        if kind == "globalgeometryrules":
            relative_geometry = len(parts) > 3 and parts[3].lower() == "relative"
        elif kind == "zone":
            require(len(parts) > 5 and all(abs(float(value or 0)) < 1e-8 for value in parts[2:6]),
                    "C IDF zone transform is not supported by the floor view")
            zone_names.add(parts[1])
        if kind == "buildingsurface:detailed":
            if parts[2].lower() not in {"floor", "wall"}:
                continue
            points = vertices(parts, 11)
            if parts[2].lower() == "floor":
                polygon = [[x, y] for x, y, _ in points]
                surface_area = abs(sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1] -
                                       polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
                                       for i in range(len(polygon)))) / 2
                require(surface_area > 0, "C IDF floor has zero area")
                floors.append({"zone": parts[4], "points": polygon})
                area += surface_area
            else:
                edge = bottom_edge(points)
                if edge:
                    walls.append({"zone": parts[4], "points": edge})
        elif kind == "fenestrationsurface:detailed" and parts[2].lower() in {"window", "door"}:
            edge = bottom_edge(vertices(parts, 9))
            if edge:
                openings.append({"type": parts[2].lower(), "points": edge})
    require(relative_geometry and floors and walls and abs(area - expected_area_m2) < 0.1,
            "C IDF floor geometry does not match the locked household area")
    zones = sorted({floor["zone"] for floor in floors})
    require(set(zones) == zone_names, "C IDF floor zones do not match the household zones")
    return {"floors": floors, "walls": walls, "openings": openings,
            "owned_zones": zones, "zone_labels": {zone: LABELS.get(zone, zone) for zone in zones},
            "source": "locked_C_IDF", "source_sha256": expected_sha,
            "floor_area_m2": round(area, 3)}
