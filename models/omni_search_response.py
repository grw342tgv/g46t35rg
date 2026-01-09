from typing import List, Optional
from pydantic import BaseModel

class GameContent(BaseModel):
    universeId: int
    name: str
    description: str
    playerCount: int
    totalUpVotes: int
    totalDownVotes: int
    emphasis: bool
    isSponsored: bool
    nativeAdData: str
    creatorName: str
    creatorHasVerifiedBadge: bool
    creatorId: int
    rootPlaceId: int
    minimumAge: int
    ageRecommendationDisplayName: str
    contentType: str
    contentId: int

class GameSearchResult(BaseModel):
    contentGroupType: str
    contents: List[GameContent]
    topicId: str

class OmniSearchResponse(BaseModel):
    searchResults: List[GameSearchResult]
    nextPageToken: Optional[str]
    filteredSearchQuery: Optional[str]
    vertical: str
    sorts: Optional[str]