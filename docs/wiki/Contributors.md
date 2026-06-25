# Contributors

GitHub Contributors - это не список людей, у которых есть доступ к репозиторию.

GitHub строит этот блок по истории Git: берет авторов коммитов, связывает email с GitHub-профилями и показывает уникальные аккаунты.

## Почему Их 7

На момент проверки GitHub API показывает 7 профилей:

| GitHub profile | Откуда взялся |
| --- | --- |
| `snoups` | автор исходной open-source базы `3xui-shop` |
| `AFETZ` | текущие AFZVPN production-коммиты |
| `BazZziliuS` | исторический upstream commit |
| `claude` | commit из ранее смерженного PR |
| `DmitryKrylovv` | исторический upstream PR |
| `Lethaquell` | исторический upstream PR |
| `Heimlet` | исторический upstream PR |

Порядок и количество contributions могут меняться после новых коммитов, merge commits и обновления GitHub cache.

## Могут Ли Они Коммитить В Репозиторий

Не обязательно. Contributors показывают авторство прошлых коммитов, а не текущие права.

Кто реально может push:

- owner репозитория;
- collaborators с write/admin доступом;
- GitHub Apps или bots с выданными правами;
- workflows, если у них есть permissions.

Проверять доступ нужно в GitHub: **Settings -> Collaborators and teams**, а не в блоке Contributors.

## Почему В Истории Больше Имен, Чем На GitHub

Локальный Git считает автора как `Name <email>`. GitHub может склеить несколько email в один профиль.

Пример:

- `Ilay <isnoups@gmail.com>`;
- `Ilay <39022810+snoups@users.noreply.github.com>`;

оба отображаются как GitHub contributor `snoups`.
