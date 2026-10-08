"""Experimental unified read contract; operation APIs keep their namespaces."""
from fastapi import APIRouter


def router_for(service):
    router = APIRouter(prefix='/api/v2/network', tags=['통합 관측소'])

    @router.get('/stations')
    def stations(mode: str = 'current', replay_id: str | None = None,
                 as_of: str | None = None, region_code: str | None = None):
        return service.stations(mode=mode, replay_id=replay_id, as_of=as_of, region_code=region_code)

    @router.get('/stations/{station_id}/history')
    def history(station_id: str, mode: str = 'current', replay_id: str | None = None,
                as_of: str | None = None):
        return service.history(station_id, mode=mode, replay_id=replay_id, as_of=as_of)

    @router.get('/pipeline')
    def pipeline(station_id: str, mode: str = 'current', replay_id: str | None = None,
                 as_of: str | None = None):
        return service.pipeline(station_id, mode=mode, replay_id=replay_id, as_of=as_of)

    return router
