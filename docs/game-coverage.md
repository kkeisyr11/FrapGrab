# Automatic clipping coverage

The game selector shows integrations that exist in Frap Grab. Support in another recorder does not supply Frap Grab with that game's events.

| Game or game group | Frap Grab status and event source |
| --- | --- |
| War Dogs | Released. Player HUD detection. Death and knockdown recognition is optional and uses OCR. |
| Rocket League | Released beta. Local Stats API for goals, assists, and saves. |
| Counter-Strike 2, Dota 2 | Source preview. Local Valve Game State Integration for kills, assists, and deaths. Tested against simulated match data. Live match checks pending. |
| League of Legends | Source preview. Riot Live Client Data API. Live match check and Riot registration pending. |
| Call of Duty: Warzone, Apex Legends, Fortnite, PUBG: Battlegrounds | Source experiments for the English victory banner. Real match footage and in-game verification pending. Other events and Call of Duty editions require separate integrations. |
| Battlefield 6 / REDSEC, Brawlhalla, Call of Duty: Black Ops 7, Delta Force, Destiny 2, Diablo IV, Escape from Tarkov, Fall Guys, Genshin Impact, Helldivers 2, Marvel Rivals, Overwatch 2, Path of Exile 2, Rainbow Six Siege X, Street Fighter 6, Valorant | SteelSeries lists these titles. Independent integrations pending. |
| 3D Aim Trainer | Listed by SteelSeries. Independent integration pending. |
| EA Sports FC Online, Rematch, RuneScape: Dragonwilds, War Thunder, YAPYAP | Listed by Medal. Independent integration pending. |
| GTA V / FiveM, Minecraft | Medal documents server-provided events. Frap Grab integration pending. |
| R.E.P.O. | Medal documents a game plugin. Frap Grab integration pending. |
| Roblox, MultiVersus | Listed on older Medal and SteelSeries help pages, respectively. Confirm current coverage before targeting them. |

For each integration, check in-game event delivery, duplicate suppression, reconnects, and whether a saved clip includes the event and its context. Only add a game topic to GitHub once the corresponding installer is available.

## References

- [SteelSeries Moments game list](https://support.steelseries.com/hc/en-us/articles/360051565892-Which-games-support-Moments-autoclip)
- [SteelSeries Moments event support](https://support.steelseries.com/hc/en-us/articles/360060115032-What-is-auto-clip-with-SteelSeries-Moments)
- [Battlefield 6 and REDSEC](https://support.steelseries.com/hc/en-us/articles/40149948138509-Moments-for-Battlefield-6)
- [Black Ops 7 in SteelSeries GG](https://techblog.steelseries.com/2025/12/02/GG-notes-100.0.0.html)
- [Delta Force in SteelSeries GG](https://techblog.steelseries.com/2026/05/20/GG-notes-111.0.0.html)
- [Street Fighter 6](https://support.steelseries.com/hc/en-us/articles/43972102589453-Auto-Clipping-for-Street-Fighter-6)
- [Medal auto clipping and supported games](https://medal.tv/auto-clipping)
- [Medal help article with the older Roblox listing](https://support.medal.tv/support/solutions/articles/48001167701)
- [Rocket League Stats API](https://www.rocketleague.com/developer/stats-api)
- [FiveM server events](https://docs.fivem.net/docs/resources/baseevents/)
- [Paper server event listeners](https://docs.papermc.io/paper/dev/event-listeners/)
- [Valve Dota 2 Game State Integration launch option](https://store.steampowered.com/news/posts/?appids=570&enddate=1648162911&feed=steam_community_announcements)
- [Counter-Strike 2 GSI reference implementation](https://github.com/antonpup/CounterStrike2GSI)
