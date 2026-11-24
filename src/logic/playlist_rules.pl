% База знань та логічні правила для Куратора плейлистів (Етап 4 — Prolog).
% Використовується з Python через SWI-Prolog / pyswip на живому шляху генерації плейлиста.

:- dynamic favorite_artist/1.
:- dynamic similar/2.
:- dynamic banned/1.
:- dynamic track_info/4.

% --- Допоміжні предикати ---

% Виконавець дозволений, якщо він не позначений як заборонений.
allowed_artist(Artist) :-
    \+ banned(Artist).

% --- 1. Пошук ланцюжків схожості (<= MaxSteps кроків від улюбленого) ---

% Пошук шляху схожості у спрямованому графі без циклів та без заборонених виконавців.
similarity_path(From, To, MaxSteps, Path) :-
    allowed_artist(From),
    allowed_artist(To),
    dfs_path(From, To, MaxSteps, [From], RevPath),
    reverse(RevPath, Path).

dfs_path(Current, Current, _StepsLeft, Visited, Visited).
dfs_path(Current, Target, StepsLeft, Visited, Path) :-
    StepsLeft > 0,
    similar(Current, Next),
    allowed_artist(Next),
    \+ member(Next, Visited),
    NextSteps is StepsLeft - 1,
    dfs_path(Next, Target, NextSteps, [Next | Visited], Path).

% Рекомендує нового виконавця Target (не з улюблених і не забороненого),
% якщо існує шлях схожості довжиною від 1 до MaxSteps кроків від улюбленого виконавця.
recommend_discovery(Target, MaxSteps, Path) :-
    favorite_artist(Fav),
    allowed_artist(Fav),
    dfs_path(Fav, Target, MaxSteps, [Fav], RevPath),
    reverse(RevPath, Path),
    Path = [_, _ | _],
    \+ favorite_artist(Target),
    allowed_artist(Target).

% --- 2. Сумісність настроїв для плавних переходів ---

mood_group('енергійний', active).
mood_group('веселий', active).
mood_group('спокійний', calm).
mood_group('сумний', calm).
mood_group('зосереджений', neutral).
mood_group('unknown', neutral).

smooth_mood_transition(M, M) :- !.
smooth_mood_transition(M1, M2) :-
    mood_group(M1, G),
    mood_group(M2, G), !.
smooth_mood_transition(M1, M2) :-
    (mood_group(M1, neutral) ; mood_group(M2, neutral)), !.

% --- 3. Задача лінійного сусідства та валідація послідовності ---

% Перевіряє, що послідовність треків не містить заборонених виконавців
% і жоден виконавець не звучить двічі поспіль.
valid_track_sequence([]).
valid_track_sequence([Id]) :-
    track_info(Id, Artist, _Mood, _Source),
    allowed_artist(Artist).
valid_track_sequence([Id1, Id2 | Rest]) :-
    track_info(Id1, A1, _M1, _S1),
    track_info(Id2, A2, _M2, _S2),
    allowed_artist(A1),
    allowed_artist(A2),
    A1 \= A2,
    valid_track_sequence([Id2 | Rest]).

% Залишає у списку лише треки дозволених (не заборонених) виконавців.
filter_allowed_tracks([], []).
filter_allowed_tracks([Id | Rest], [Id | FilteredRest]) :-
    track_info(Id, Artist, _Mood, _Source),
    allowed_artist(Artist), !,
    filter_allowed_tracks(Rest, FilteredRest).
filter_allowed_tracks([_Id | Rest], FilteredRest) :-
    filter_allowed_tracks(Rest, FilteredRest).

% Упорядкування послідовності треків без повторів виконавців підряд (де це можливо)
% та з урахуванням плавності переходів настрою.
arrange_playlist(TrackIds, OrderedIds) :-
    filter_allowed_tracks(TrackIds, AllowedIds),
    arrange_loop(AllowedIds, none, none, OrderedIds).

arrange_loop([], _PrevArtist, _PrevMood, []).
arrange_loop(Remaining, PrevArtist, PrevMood, [Pick | RestOrdered]) :-
    pick_next_track(Remaining, PrevArtist, PrevMood, Pick, Rest),
    track_info(Pick, NextArtist, NextMood, _Source),
    arrange_loop(Rest, NextArtist, NextMood, RestOrdered).

% Пріоритет 1: інший виконавець + плавний перехід настрою (перевага виконавцю з більшою кількістю треків).
pick_next_track(Remaining, PrevArtist, PrevMood, Pick, Rest) :-
    findall(NegCount-Id, (
        member(Id, Remaining),
        track_info(Id, Artist, Mood, _Source),
        Artist \= PrevArtist,
        (PrevMood == none ; smooth_mood_transition(PrevMood, Mood)),
        count_artist_tracks(Remaining, Artist, Count),
        NegCount is -Count
    ), Pairs),
    Pairs \= [], !,
    keysort(Pairs, [_BestNeg-Pick | _]),
    select_once(Pick, Remaining, Rest).

% Пріоритет 2: будь-який інший виконавець (уникаємо повтору виконавця підряд).
pick_next_track(Remaining, PrevArtist, _PrevMood, Pick, Rest) :-
    findall(NegCount-Id, (
        member(Id, Remaining),
        track_info(Id, Artist, _Mood, _Source),
        Artist \= PrevArtist,
        count_artist_tracks(Remaining, Artist, Count),
        NegCount is -Count
    ), Pairs),
    Pairs \= [], !,
    keysort(Pairs, [_BestNeg-Pick | _]),
    select_once(Pick, Remaining, Rest).

% Пріоритет 3 (запасний): коли в залишку лишився лише один виконавець.
pick_next_track([Pick | Rest], _PrevArtist, _PrevMood, Pick, Rest).

count_artist_tracks([], _Artist, 0).
count_artist_tracks([Id | Rest], Artist, Count) :-
    track_info(Id, A, _Mood, _Source),
    (A == Artist -> Inc = 1 ; Inc = 0),
    count_artist_tracks(Rest, Artist, SubCount),
    Count is SubCount + Inc.

select_once(X, [X | Rest], Rest) :- !.
select_once(X, [Y | Rest], [Y | RestOut]) :-
    select_once(X, Rest, RestOut).
