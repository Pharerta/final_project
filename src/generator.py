from datetime import date
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from core.graph import explain_recommendation_chain
from core.playlist import (
    avoid_adjacent_repeats,
    calculate_track_weight,
    fill_budget,
    generate_playlist_data,
)
from logic.prolog_engine import PrologEngine, PrologPlaylistPlan
from models import AudioTrack, LibraryTrack, Mood, Playlist


class PlaylistGenerator:
    """Генератор плейлистів: ООП-фасад, що поєднує функціональне ядро (Етап 3) та Prolog (Етап 4).

    Наскрізний шлях генерації:
    ООП-інтерфейс -> Prolog (пошук ланцюжків схожості <= 3) ->
    Функціональне ядро (зважування, фільтрація, добір під бюджет) ->
    Prolog (валідація послідовності без сусідніх повторів) -> ООП Playlist.
    """

    RECENCY_CAP_DAYS = 30  # після цього «свіжість» більше не зростає

    def __init__(
        self,
        library: Iterable[LibraryTrack],
        discoveries: Iterable[AudioTrack] = (),
        banned_artists: Iterable[str] = (),
        similarity_graph: Optional[Mapping[str, Sequence[str]]] = None,
        prolog_engine: Optional[PrologEngine] = None,
    ):
        self._library: List[LibraryTrack] = list(library)
        self._discoveries: List[AudioTrack] = list(discoveries)
        self._banned = {name.strip().casefold() for name in banned_artists}
        self._similarity_graph: Dict[str, Tuple[str, ...]] = {
            str(artist).strip(): tuple(str(rel).strip() for rel in related)
            for artist, related in (similarity_graph or {}).items()
            if str(artist).strip()
        }
        self._prolog = prolog_engine or PrologEngine()
        self.last_prolog_plan: Optional[PrologPlaylistPlan] = None

    def _is_banned(self, artist: str) -> bool:
        return artist.strip().casefold() in self._banned

    def _weight(self, track: LibraryTrack, today: date) -> float:
        """Розрахунок ваги через чисту функцію ядра."""
        return calculate_track_weight(track, today, recency_cap_days=self.RECENCY_CAP_DAYS)

    @staticmethod
    def _fill(candidates: List[AudioTrack], budget_sec: int) -> List[AudioTrack]:
        """Жадібний відбір через чисту функцію ядра fill_budget."""
        return list(fill_budget(candidates, budget_sec))

    @staticmethod
    def _avoid_repeats(tracks: List[AudioTrack]) -> List[AudioTrack]:
        """Усунення повторів через чисту функцію ядра avoid_adjacent_repeats."""
        return list(avoid_adjacent_repeats(tracks))

    def generate(
        self,
        duration_min: int,
        mood: Optional[Mood | str] = None,
        new_percent: int = 30,
        today: Optional[date] = None,
        name: str = "Smart Playlist",
    ) -> Playlist:
        """Генерує плейлист через поєднання функціонального ядра та Prolog-рушія."""
        if duration_min <= 0:
            raise ValueError("Тривалість має бути додатною")
        if not 0 <= new_percent <= 100:
            raise ValueError("Відсоток нових виконавців має бути від 0 до 100")

        parsed_mood_str = Mood.parse(mood).value if mood is not None else None
        favorite_artists = list(
            dict.fromkeys(
                t.artist.strip()
                for t in self._library
                if t.artist.strip() and not self._is_banned(t.artist)
            )
        )

        # 1. Логічна парадигма (Prolog): пошук досяжних нових виконавців у графі схожості
        discovery_paths: Dict[str, Tuple[str, ...]] = {}
        explanations: Dict[str, str] = {}
        eligible_discoveries: Sequence[AudioTrack] = self._discoveries

        if self._similarity_graph and favorite_artists:
            discovery_paths = self._prolog.find_recommendations(
                favorites=favorite_artists,
                similarity_graph=self._similarity_graph,
                banned_artists=self._banned,
                max_steps=3,
            )
            explanations = {
                artist_key: explain_recommendation_chain(path)
                for artist_key, path in discovery_paths.items()
            }
            eligible_discoveries = [
                track
                for track in self._discoveries
                if track.artist.strip().casefold() in discovery_paths
            ]

        # 2. Функціональне ядро: чиста фільтрація, зважування та добір у бюджет часу
        playlist_data = generate_playlist_data(
            library=self._library,
            discoveries=eligible_discoveries,
            duration_min=duration_min,
            mood=parsed_mood_str,
            new_percent=new_percent,
            banned_artists=self._banned,
            today=today,
            name=name,
        )

        # 3. Логічна парадигма (Prolog): валідація та впорядкування послідовності треків
        ordered_indices, is_valid = self._prolog.arrange_tracks(
            tracks=playlist_data.tracks,
            banned_artists=self._banned,
            favorite_artists=favorite_artists,
        )

        selected_tracks = list(playlist_data.tracks)
        if len(ordered_indices) == len(selected_tracks) and set(ordered_indices) == set(range(len(selected_tracks))):
            final_tracks = [selected_tracks[i] for i in ordered_indices]
        else:
            final_tracks = selected_tracks

        facts_count = (
            len(favorite_artists)
            + sum(len(v) for v in self._similarity_graph.values())
            + len(self._banned)
            + len(selected_tracks)
        )
        self.last_prolog_plan = PrologPlaylistPlan(
            ordered_indices=ordered_indices,
            is_sequence_valid=is_valid,
            discovery_paths=discovery_paths,
            explanations=explanations,
            facts_count=facts_count,
        )

        # 4. Повернення ООП-результату користувачу з поясненнями рекомендацій
        playlist = Playlist(playlist_data.name)
        for track in final_tracks:
            playlist.add_track(track)
            reason = explanations.get(track.artist.strip().casefold())
            if reason:
                playlist.set_explanation(track.artist, reason)
        return playlist
