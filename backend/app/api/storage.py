from fastapi import Request, Response

from app.repositories.news_repository import PostgresNewsRepository


def get_news_repository(request: Request, response: Response) -> PostgresNewsRepository | None:
    repository = request.app.state.news_repository
    response.headers.update(repository.headers() if repository else {"X-News-Storage": "memory"})
    return repository
