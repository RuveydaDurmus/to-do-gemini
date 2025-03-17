from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Annotated
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from starlette import status
from starlette.responses import RedirectResponse
from dotenv import load_dotenv
from models import Base, Todo
from database import engine, SessionLocal
from pathlib import Path
from .auth import get_current_user
import google.generativeai as genai
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage,AIMessage
import markdown

router = APIRouter(
    prefix="/todo",
    tags=["Todo"]
)

templates = Jinja2Templates(directory="templates")

class TodoRequest(BaseModel):
    title: str = Field(min_length=3)
    description: str = Field(min_length=3, max_length=2000)
    priority: int = Field(gt=0, lt=6)
    complete: bool

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[dict, Depends(get_current_user)]

def redirect_to_login():
    redirect_response =  RedirectResponse(url="/auth/login-page",status_code=status.HTTP_302_FOUND)
    redirect_response.delete_cookie("access_token")
    return redirect_response

@router.get("/todo-page")
async def render_todo_page(request: Request,db: db_dependency):
    try:
        user = await get_current_user(request.cookies.get('access_token'))
        if user is None:
            return redirect_to_login()
        todos = db.query(Todo).filter(Todo.owner_id == user.get("id")).all()
        return templates.TemplateResponse("todo.html", {"request": request, "todos": todos, "user": user})
    except:
        return redirect_to_login()

@router.get("/add-todo-page")
async def render_add_todo_page(request: Request):
    try:
        user = await get_current_user(request.cookies.get('access_token'))
        if user is None:
            return redirect_to_login()
        return templates.TemplateResponse("add-todo.html", {"request": request, "user": user})
    except:
        return redirect_to_login()


@router.get("/edit-todo-page/{todo_id}")
async def render_edit_todo_page(request: Request,todo_id:int,db: db_dependency):
    try:
        user = await get_current_user(request.cookies.get('access_token'))
        if user is None:
            return redirect_to_login()
        todo = db.query(Todo).filter(Todo.id == todo_id).first()
        return templates.TemplateResponse("edit-todo.html", {"request": request, "todo": todo, "user": user})
    except:
        return redirect_to_login()



@router.get("/")
async def read_all(user:user_dependency,db: db_dependency):
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return db.query(Todo).filter(Todo.owner_id == user.get("id")).all()

@router.get("/todo/{todo_id}")
async def get_by_id(user:user_dependency,db:db_dependency, todo_id:int = Path(gt=0)):
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    todo = db.query(Todo).filter(Todo.id == todo_id).filter(Todo.owner_id == user.get("id")).first()
    if todo is not None:
        return todo
    raise HTTPException(status_code=404)

@router.post("/todo")
async def create_todo(todo: TodoRequest,user:user_dependency, db: db_dependency):
    todo_data = todo.dict()
    new_todo = Todo(**todo_data,owner_id=user.get("id"))
    new_todo.description = create_todo_with_gemini(new_todo.description)
    db.add(new_todo)
    db.commit()


@router.put("/todo/{todo_id}")
async def update_todo(user:user_dependency,db: db_dependency,todo: TodoRequest, todo_id: int = Path(gt=0)):
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    todo = db.query(Todo).filter(Todo.id == todo_id).filter(Todo.owner_id == user.get("id")).first()
    if todo is None:
        raise HTTPException(status_code=404)
    todo.title = todo.title
    todo.description = todo.description
    todo.priority = todo.priority
    todo.complete = todo.complete
    db.add(todo)
    db.commit()

@router.delete("/todo/{todo_id}")
async def delete_todo(user:user_dependency,db: db_dependency, todo_id: int = Path(gt=0)):
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    todo = db.query(Todo).filter(Todo.id == todo_id).filter(Todo.owner_id == user.get("id")).first()
    if todo is None:
        raise HTTPException(status_code=404)
    db.delete(todo)
    db.commit()
    return {"message": "Todo deleted successfully"}

def markdown_to_text(markdown_string:str):
    html = markdown.markdown(markdown_string)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()
    return text


def create_todo_with_gemini(todo_string:str):
    load_dotenv()
    genai.configure(api_key=os.getenv("GENAI_API_KEY"))
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro")
    response = llm.invoke([
        HumanMessage(content="I will provide a todo item to add my todo list. What i want you to do is to create a longer and comprehensice description of that todo item. My next message will be my todo."),
        HumanMessage(content=todo_string),
    ])

    return markdown_to_text(response.content)


