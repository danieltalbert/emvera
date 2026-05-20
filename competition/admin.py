from django.contrib import admin
from .models import Competition, CompetitionParticipant, MiniGame, MiniGameResult


class ParticipantInline(admin.TabularInline):
    model = CompetitionParticipant
    extra = 0
    readonly_fields = ('joined_at',)


class MiniGameInline(admin.TabularInline):
    model = MiniGame
    extra = 0
    readonly_fields = ('created_at', 'finished_at')


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'created_by', 'participant_count', 'created_at')
    list_filter = ('status',)
    inlines = [ParticipantInline, MiniGameInline]

    def participant_count(self, obj):
        return obj.participants.count()
    participant_count.short_description = 'Players'


@admin.register(MiniGame)
class MiniGameAdmin(admin.ModelAdmin):
    list_display = ('competition', 'game_type', 'status', 'winner', 'bonus_amount', 'created_at')
    list_filter = ('status', 'game_type')
    readonly_fields = ('created_at', 'finished_at')


@admin.register(MiniGameResult)
class MiniGameResultAdmin(admin.ModelAdmin):
    list_display = ('mini_game', 'participant', 'score', 'submitted_at')
    readonly_fields = ('submitted_at',)
