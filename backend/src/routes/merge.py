from fastapi import APIRouter, Depends
from src.schemas.merge import MergeCreate
from src.controllers import merge as controller
from src.utils.dependencies import current_user,writer
router=APIRouter(prefix="/merges",tags=["merges"])

@router.get("")
def listing(user=Depends(current_user)): return controller.listing()

@router.post("",status_code=201)
def create(body:MergeCreate,user=Depends(writer)): return controller.create(body)

@router.get("/{ident}/download")
def download(ident:int,user=Depends(current_user)):
    return controller.download(ident)
