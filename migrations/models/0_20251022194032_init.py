from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "users" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "discord_id" BIGINT NOT NULL UNIQUE,
    "first_name" TEXT NOT NULL,
    "last_name" TEXT NOT NULL,
    "group" TEXT NOT NULL
) /* Модель пользователя Discord, сохранённого в базе данных. */;
CREATE TABLE IF NOT EXISTS "labworks" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "lab_number" INT NOT NULL,
    "file_url" TEXT,
    "status" VARCHAR(20) NOT NULL DEFAULT 'отправлено',
    "feedback" TEXT,
    "submitted_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "teacher_message_id" BIGINT,
    "teacher_channel_id" BIGINT,
    "user_id" INT NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_labworks_user_id_194b61" UNIQUE ("user_id", "lab_number")
) /* Таблица лабораторных работ студентов. */;
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSON NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "eJztmVtv0zAUgP9KlKchjSlN07Xw1m3dqNg6NApMGyhyYjeN5tglcbRVqP8d23Ea59KyFS"
    "gD+hIl5+LY3zl1j0++mRGFCCcH58D7ROM787XxzSQgQvymqto3TDCbFQohYMDD0hYD754b"
    "SSHwEhYDn3H5BOAEcRFEiR+HMxZSIqw/p5Zj2+LatuS1Ja+evPbE1TnMtIam0E2RNLIKuW"
    "PX5FDeS1+nY1QdSgPZmbpVjOS0pdqR1442nvaetn0g1gupzxcckuDfW1pKwq8pchkNEJui"
    "mC/w9tZME363L2PukjTy+NOXL/w5JBA9oEQYicfZnTsJEYalnAqh8JRyl81nUjYk7FQaCp"
    "ae61OcRqQwns3ZlJKldUiYkAaIoBgwJIZncSqSjKQYq3zM8y6bf2GSTVHzgWgCUixSVXjX"
    "MjUXahFWIp8SkeV8NolcYCDe8tJuOV2n1z50eoKPEC0l3UW2vGLtmaMkMBqbC6kHDGQWEm"
    "PBTWP9eH5lpx9zzKmtA5kLCpLFb/w5oSzQTUKM3DTGdXBj9LCCnO5T4can+ghuKr22iG0N"
    "k/HgeizmHCXJVywEo4/9q+M3/au9i/71C6mZK8355egsN6d8E89299Hx+eVRBWvCAEuTOt"
    "TjKYiboRYeGyHdKBVNfSeU95PabmlrG7G2HbaR+RNJHIEHFyMSsKnIXGtNdPJY2NaLCnWl"
    "saWqktQIQQ/4d09Kas1nl9TNSZ16Ucg4ABewOtoTjoaFEVqR3hXfCmKonA/ym2e6+8YIwE"
    "uC5yre6yIwvBi8H/cv3pXCcNIfD4TGLoUgl+4dVpJ8OYjxaTh+Y4hH4+ZyNJAEacKCWL6x"
    "sBvfmGJOIGXUJfTeBVD7O8+lOZhScNOZQL9JaMueu8D+0cCqyRdxZQj4vDh1I5QkIEBuU4"
    "15FAYry6Rm/43Kpe3vkKpaemXb7XbXttqHvY7T7XZ61rJsqqvW1U9HwzNRQpVCWa+pcmT+"
    "FBCC8MbIy/475GuQi1NXI+eVkDWP/6n2F2fPyV3jKSo/uZYBntIYhQF5i+aS45DPCBAfNX"
    "BTHZEPapjnx2+R50AuLX4gMbhfnsf11ODL44tCLCve+++P+ycDU0IUteI9iKFboik01KYV"
    "ydK2rorsqCoBhO+zUK1CzFkH29CCyoGv7j+JBT2h+dTytVaH3gjJWiq+URwVlJFSyPuu3i"
    "ep9Wn0gSbGSZj4NIb7WhdGHUc6tYOIPHZ0WtoRBGpvyro2KJta1tVRjR5Lm1XWDVJrsqpD"
    "5S2j5r7Vjsp+Y8tr19z6vc0tmGXDk6uIst+v+Y/bEsstFw+TME6YK59qhNd1wXSv7TVt/q"
    "6eAQYboC057cg2kw1ims6eQnXpsCNaEK3Vw6tru9L3huX3vMqGrDxP314hDOSCVxbK2qfD"
    "Z8u+Visvfn2Fu/gOTXMzRQ=="
)
