"""Функції вищого порядку та утиліти композиції функцій."""

from datetime import date
from functools import reduce
from typing import Any, Callable, Iterable, Protocol, Sequence, Tuple, TypeVar

T = TypeVar("T")


class SupportsLt(Protocol):
    """Протокол для значень, які підтримують порівняння під час сортування."""

    def __lt__(self, other: Any, /) -> bool: ...


K = TypeVar("K", bound=SupportsLt)


def compose(*funcs: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """Класична математична композиція функцій справа наліво: (f . g . h)(x) = f(g(h(x))).

    Функція вищого порядку, яка приймає довільну кількість чистих функцій
    і повертає нову функцію — їхню послідовну композицію.
    """
    if not funcs:
        return lambda x: x
    return reduce(lambda f, g: lambda x: f(g(x)), funcs)


def pipe(initial_value: Any, *funcs: Callable[[Any], Any]) -> Any:
    """Конвеєр функціональної обробки зліва направо: pipe(x, f, g) == g(f(x))."""
    return reduce(lambda val, func: func(val), funcs, initial_value)


def combine_predicates(*predicates: Callable[[T], bool]) -> Callable[[T], bool]:
    """Функція вищого порядку: об'єднує декілька предикатів за правилом логічного AND.

    Повертає новий чистий предикат, який повертає True лише тоді,
    коли кожен із переданих предикатів повертає True для переданого елемента.
    """

    def combined(item: T) -> bool:
        return all(p(item) for p in predicates)

    return combined


def filter_by(predicate: Callable[[T], bool]) -> Callable[[Iterable[T]], Tuple[T, ...]]:
    """Функція вищого порядку: приймає предикат і повертає функцію фільтрації послідовності.

    Повертає незмінний кортеж елементів, що задовольняють умову.
    """

    def filter_func(items: Iterable[T]) -> Tuple[T, ...]:
        return tuple(item for item in items if predicate(item))

    return filter_func


def sort_by_key(key_fn: Callable[[T], K], reverse: bool = False) -> Callable[[Sequence[T]], Tuple[T, ...]]:
    """Функція вищого порядку: приймає функцію вилучення ключа і повертає функцію сортування.

    Повертає новий незмінний відсортований кортеж, не модифікуючи оригінал.
    """

    def sort_func(items: Sequence[T]) -> Tuple[T, ...]:
        return tuple(sorted(items, key=key_fn, reverse=reverse))

    return sort_func


def make_weight_scorer(today: date, recency_cap_days: int = 30) -> Callable[[Any], float]:
    """Функція вищого порядку: фабрика чистих функцій зважування треків.

    Замикає дату розрахунку та ліміт давності, повертаючи чисту функцію оцінки ваги треку:
        weight = rating * (1 + min(days_since_played, cap) / cap)
    """
    cap = max(1, recency_cap_days)

    def scorer(track: Any) -> float:
        last_played = getattr(track, "last_played", None)
        if isinstance(last_played, date):
            days = max((today - last_played).days, 0)
        else:
            days = cap
        rating_val = getattr(track, "rating", 3)
        rating = int(rating_val) if isinstance(rating_val, (int, float)) else 3
        return float(rating * (1.0 + min(days, cap) / cap))

    return scorer
