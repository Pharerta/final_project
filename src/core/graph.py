"""Чисті рекурсивні алгоритми для роботи з графом схожості виконавців.

Граф схожості має рекурсивну структуру (виконавець -> схожі виконавці -> ...).
Усі функції є чистими:
- Не містять побічних ефектів, викликів мережі, print або глобального стану.
- Працюють виключно з незмінними структурами (Mapping, Tuple, FrozenSet).
- Безпечно обробляють цикли в графі за рахунок передачі незмінного кортежу відвіданих вершин.
"""
from typing import FrozenSet, Mapping, Optional, Sequence, Tuple


def _lookup_neighbors(graph: Mapping[str, Sequence[str]], artist: str) -> Tuple[str, ...]:
    """Допоміжна чиста функція пошуку сусідів у графі без урахування регістру."""
    if artist in graph:
        return tuple(graph[artist])
    target_key = artist.strip().casefold()
    for key, neighbors in graph.items():
        if key.strip().casefold() == target_key:
            return tuple(neighbors)
    return ()


def find_recommendation_chain_recursive(
    graph: Mapping[str, Sequence[str]],
    current: str,
    target: str,
    banned: FrozenSet[str] = frozenset(),
    visited: Tuple[str, ...] = (),
    max_depth: int = 3,
) -> Optional[Tuple[str, ...]]:
    """Рекурсивний пошук найкоротшого ланцюжка схожості між двома виконавцями.

    Параметри:
        graph: незмінне відображення імені виконавця на послідовність схожих.
        current: поточний виконавець (початок або проміжний вузол).
        target: цільовий виконавець, якого шукаємо.
        banned: множина заборонених імен виконавців (у casefold).
        visited: незмінний кортеж уже відвіданих вершин у поточному шляху (для захисту від циклів).
        max_depth: максимальна дозволена глибина ланцюжка (за замовчуванням 3).

    Повертає:
        Кортеж імен виконавців від current до target (наприклад, ('Blur', 'Gorillaz', 'Pulp'))
        або None, якщо шлях не знайдено або перевищено max_depth.
    """
    current_key = current.strip().casefold()
    target_key = target.strip().casefold()

    # Заборонений виконавець не може бути частиною валідного ланцюжка
    if current_key in banned:
        return None

    # Цикл: якщо вже були тут на цьому шляху, перериваємо рекурсію
    if any(v.strip().casefold() == current_key for v in visited):
        return None

    new_visited = visited + (current,)

    # Базовий випадок 1: дісталися до цілі
    if current_key == target_key:
        return new_visited

    # Базовий випадок 2: вичерпали ліміт кроків
    if len(visited) >= max_depth:
        return None

    neighbors = _lookup_neighbors(graph, current)
    shortest_path: Optional[Tuple[str, ...]] = None

    # Рекурсивний крок: обхід сусідів
    for neighbor in neighbors:
        neighbor_key = neighbor.strip().casefold()
        if neighbor_key in banned:
            continue
        if any(v.strip().casefold() == neighbor_key for v in new_visited):
            continue

        candidate_path = find_recommendation_chain_recursive(
            graph=graph,
            current=neighbor,
            target=target,
            banned=banned,
            visited=new_visited,
            max_depth=max_depth,
        )

        if candidate_path is not None:
            if shortest_path is None or len(candidate_path) < len(shortest_path):
                shortest_path = candidate_path

    return shortest_path


def collect_reachable_artists_recursive(
    graph: Mapping[str, Sequence[str]],
    current: str,
    banned: FrozenSet[str] = frozenset(),
    visited: Tuple[str, ...] = (),
    max_depth: int = 3,
) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    """Рекурсивно знаходить усіх досяжних виконавців у межах max_depth та шляхи до них.

    Повертає незмінний кортеж пар (ім'я_виконавця, повний_шлях).
    """
    current_key = current.strip().casefold()
    if current_key in banned:
        return ()

    if any(v.strip().casefold() == current_key for v in visited):
        return ()

    new_visited = visited + (current,)
    if len(visited) >= max_depth:
        return ()

    neighbors = _lookup_neighbors(graph, current)
    results: list[Tuple[str, Tuple[str, ...]]] = []

    for neighbor in neighbors:
        neighbor_key = neighbor.strip().casefold()
        if neighbor_key in banned or any(v.strip().casefold() == neighbor_key for v in new_visited):
            continue

        neighbor_path = new_visited + (neighbor,)
        results.append((neighbor, neighbor_path))

        # Рекурсивне занурення на наступний рівень
        sub_results = collect_reachable_artists_recursive(
            graph=graph,
            current=neighbor,
            banned=banned,
            visited=new_visited,
            max_depth=max_depth,
        )
        results.extend(sub_results)

    # Залишаємо найкоротший шлях для кожного унікального виконавця (без побічних ефектів)
    best_paths: dict[str, Tuple[str, ...]] = {}
    for artist, path in results:
        key = artist.strip().casefold()
        if key not in best_paths or len(path) < len(best_paths[key]):
            best_paths[key] = path

    return tuple((path[-1], path) for path in best_paths.values())


def explain_recommendation_chain(path: Sequence[str]) -> str:
    """Формує пояснення (Explainability) для ланцюжка схожості.

    Приклад:
        explain_recommendation_chain(('Blur', 'Gorillaz', 'Pulp'))
        -> "Рекомендовано, бо ви слухаєте Blur -> Gorillaz -> Pulp"
    """
    if not path:
        return ""
    if len(path) == 1:
        return f"Пряма рекомендація: {path[0]}"
    chain = " -> ".join(path)
    return f"Рекомендовано, бо ви слухаєте {chain}"

