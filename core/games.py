"""Supported game profiles. Only implemented profiles are offered in the UI."""
import sys

GAMES = {
    'wardogs': {'name': 'War Dogs', 'process_keywords': ('wardog',), 'requires_nickname': True},
    'rocket_league': {'name': 'Rocket League', 'process_keywords': ('rocketleague.exe',), 'requires_nickname': True},
}
# Keep new integrations in the source until verified in live matches.
if not getattr(sys, "frozen", False):
    GAMES.update({
        'cs2': {'name': 'Counter-Strike 2', 'process_keywords': ('cs2.exe',), 'requires_nickname': False},
        'dota2': {'name': 'Dota 2', 'process_keywords': ('dota2.exe',), 'requires_nickname': False},
        'league': {'name': 'League of Legends', 'process_keywords': ('league of legends.exe',), 'requires_nickname': False},
        'fortnite': {'name': 'Fortnite', 'process_keywords': ('fortniteclient-win64-shipping.exe',), 'requires_nickname': False},
        'pubg': {'name': 'PUBG: Battlegrounds', 'process_keywords': ('tslgame.exe',), 'requires_nickname': False},
        'apex': {'name': 'Apex Legends', 'process_keywords': ('r5apex.exe', 'r5apex_dx12.exe'), 'requires_nickname': False},
        'warzone': {'name': 'Call of Duty: Warzone', 'process_keywords': ('cod.exe',), 'requires_nickname': False},
    })

DEFAULT_GAME = 'wardogs'
ROCKET_STATS_PORT = 49124
PROFILE_KEYS = ('gamertag','pixel_profile','killfeed_enabled','detection_mode',
                'killfeed_region','auto_hud','mic_enabled','mic_threshold','mic_cooldown',
                'clip_before_kill','clip_after_kill','clip_events','assist_near_seconds','rocket_stats_port','gsi_token')

GAME_EVENTS = {
    'wardogs': ('kill', 'assist', 'death', 'knockdown', 'downed'),
    'rocket_league': ('goal', 'assist', 'save'),
    'league': ('kill', 'assist'),
    'cs2': ('kill', 'assist', 'death'),
    'dota2': ('kill', 'assist', 'death'),
    'fortnite': ('win',),
    'pubg': ('win',),
    'apex': ('win',),
    'warzone': ('win',),
}


def requires_nickname(game_id=DEFAULT_GAME):
    return GAMES.get(game_id,GAMES[DEFAULT_GAME]).get('requires_nickname',True)


def uses_hud(game_id):
    return game_id == DEFAULT_GAME


def select_game(config,game_id):
    from .config import DEFAULT_CONFIG,validate_config
    if game_id not in GAMES:raise ValueError('Unsupported game profile')
    result=validate_config(config)
    if result['game_id']==game_id:return result
    profiles={key:value.copy() for key,value in result['game_profiles'].items()}
    profiles[result['game_id']]={key:result[key] for key in PROFILE_KEYS}
    target={key:DEFAULT_CONFIG[key] for key in PROFILE_KEYS}
    target.update(profiles.get(game_id,{}))
    return validate_config({**result,**target,'game_id':game_id,'game_profiles':profiles})


def game_choices():
    return {profile['name']: key for key, profile in GAMES.items()}


def matches_game_process(name, game_id=DEFAULT_GAME):
    profile = GAMES.get(game_id)
    name = (name or '').lower()
    return bool(profile and not any(word in name for word in ('launcher', 'crash'))
                and any(name == word if word.endswith(".exe") else word in name for word in profile['process_keywords']))
