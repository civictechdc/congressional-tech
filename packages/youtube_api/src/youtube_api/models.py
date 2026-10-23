"""Pydantic models for YouTube API items and responses."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceModel(BaseModel):
    """Validate known fields without discarding new publisher fields."""

    model_config = ConfigDict(extra="allow", strict=True, validate_by_alias=True, validate_by_name=False)

    @model_validator(mode="wrap")
    @classmethod
    def preserve_alias_presence(cls, value, handler):
        result = handler(value)
        if isinstance(value, dict):
            for name, field in cls.model_fields.items():
                if field.alias and field.alias != name and name in value and field.alias not in value:
                    result.__pydantic_fields_set__.discard(name)
        return result

    def source_dict(self) -> dict:
        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)


class YoutubeRegionRestriction(SourceModel):
    allowed: list[str] | None = None
    blocked: list[str] | None = None


class YoutubeContentDetails(SourceModel):
    """The complete contentDetails part; rating authorities are native keys.

    https://developers.google.com/youtube/v3/docs/videos#contentDetails
    """
    duration: str | None = None
    dimension: str | None = None
    definition: str | None = None
    caption: str | None = None
    licensed_content: bool | None = Field(default=None, alias='licensedContent')
    region_restriction: YoutubeRegionRestriction | None = Field(default=None, alias='regionRestriction')
    content_rating: dict[str, str | list[str]] | None = Field(default=None, alias='contentRating')
    projection: str | None = None
    has_custom_thumbnail: bool | None = Field(default=None, alias='hasCustomThumbnail')


class YoutubeResourceId(SourceModel):
    kind: str | None = None
    video_id: str = Field(alias='videoId')


class YoutubePlaylistSnippet(SourceModel):
    resource_id: YoutubeResourceId = Field(alias='resourceId')
    title: str | None = None
    description: str | None = None
    published_at: str | None = Field(default=None, alias='publishedAt')


class YoutubePlaylistItem(SourceModel):
    id: str | None = None
    etag: str | None = None
    snippet: YoutubePlaylistSnippet


class YoutubeVideoSnippet(SourceModel):
    title: str | None = None
    description: str | None = None
    channel_id: str | None = Field(default=None, alias='channelId')
    channel_title: str | None = Field(default=None, alias='channelTitle')
    published_at: str | None = Field(default=None, alias='publishedAt')


class YoutubeVideoStatus(SourceModel):
    embeddable: bool | None = None


class YoutubeLiveStreamingDetails(SourceModel):
    actual_start_time: str | None = Field(default=None, alias='actualStartTime')


class YoutubeVideoItem(SourceModel):
    kind: str | None = None
    etag: str | None = None
    id: str | None = None
    snippet: YoutubeVideoSnippet | None = None
    content_details: YoutubeContentDetails | None = Field(default=None, alias='contentDetails')
    status: YoutubeVideoStatus | None = None
    live_streaming_details: YoutubeLiveStreamingDetails | None = Field(default=None, alias='liveStreamingDetails')


class YoutubeRelatedPlaylists(SourceModel):
    uploads: str


class YoutubeChannelContentDetails(SourceModel):
    related_playlists: YoutubeRelatedPlaylists = Field(alias='relatedPlaylists')


class YoutubeChannelSnippet(SourceModel):
    title: str | None = None
    description: str | None = None
    published_at: str | None = Field(default=None, alias='publishedAt')
    custom_url: str | None = Field(default=None, alias='customUrl')


class YoutubeChannelItem(SourceModel):
    id: str
    snippet: YoutubeChannelSnippet
    content_details: YoutubeChannelContentDetails = Field(alias='contentDetails')


class YoutubePageInfo(SourceModel):
    total_results: int | None = Field(default=None, alias='totalResults')
    results_per_page: int | None = Field(default=None, alias='resultsPerPage')


class YoutubeVideoResponse(SourceModel):
    kind: str | None = None
    etag: str | None = None
    next_page_token: str | None = Field(default=None, alias='nextPageToken')
    previous_page_token: str | None = Field(default=None, alias='prevPageToken')
    page_info: YoutubePageInfo | None = Field(default=None, alias='pageInfo')
    items: list[YoutubeVideoItem] = Field(default_factory=list)


class YtdlpVideoInfo(SourceModel):
    """SDK extraction result; retain every extractor-specific field unchanged."""
    id: str | None = None
    title: str | None = None
    duration: float | int | None = None
    webpage_url: str | None = None
    extractor: str | None = None
    extractor_key: str | None = None
