from fastapi.responses import Response
from src.services import merge as service

def listing(): return service.list_merges()
def create(body): return service.create(body)

def download(ident):
    return Response(service.export(ident),media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":f'attachment; filename="shared-pool-{ident}.csv"'})
