"""
utils/file_manager.py
Работа с Excel, где каждая группа — отдельный лист.
Колонки: ИМЯ | ФАМИЛИЯ
"""

import os
import pandas as pd
from config import FILE_PATH

def ensure_excel_exists():
    """Создаёт пустой Excel, если его нет."""
    if not os.path.exists(FILE_PATH):
        print(f"Файл {FILE_PATH} не найден. Создаётся новый Excel.")
        with pd.ExcelWriter(FILE_PATH, engine='openpyxl') as writer:
            df = pd.DataFrame(columns=['ИМЯ', 'ФАМИЛИЯ'])
            df.to_excel(writer, sheet_name='Неизвестные', index=False)
        print("Создан Excel с листом 'Неизвестные'.")

def get_groups():
    """Возвращает список всех групп (листов) в Excel."""
    ensure_excel_exists()
    try:
        sheets = pd.ExcelFile(FILE_PATH, engine='openpyxl').sheet_names
        return sheets
    except Exception as e:
        print(f"Ошибка при чтении групп из Excel: {e}")
        return []

def add_or_check_student(first_name, last_name, group):
    """
    Проверяет, есть ли группа и студент.
    Если группы нет — возвращает False.
    Если студент новый — добавляет его.
    Возвращает True, если группа существует.
    """
    ensure_excel_exists()
    try:
        excel_data = pd.read_excel(FILE_PATH, sheet_name=None, engine='openpyxl')
        if group not in excel_data:
            return False  # Группа не найдена

        df = excel_data[group]
        mask = (df['ИМЯ'].str.lower() == first_name.lower()) & (df['ФАМИЛИЯ'].str.lower() == last_name.lower())
        if not mask.any():
            # Добавляем нового студента
            new_row = pd.DataFrame([[first_name, last_name]], columns=['ИМЯ', 'ФАМИЛИЯ'])
            df = pd.concat([df, new_row], ignore_index=True)
            excel_data[group] = df
            with pd.ExcelWriter(FILE_PATH, engine='openpyxl') as writer:
                for sheet_name, sheet_df in excel_data.items():
                    sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Добавлен {first_name} {last_name} в группу {group}.")
        else:
            print(f"{first_name} {last_name} уже присутствует в группе {group}.")
        return True
    except Exception as e:
        print(f"Ошибка при добавлении/проверке студента: {e}")
        return False
    
def ensure_group_sheet(group_name: str) -> bool:
    """
    Гарантирует наличие листа Excel для группы.
    Возвращает True, если лист создан заново; False, если уже существовал.
    """
    ensure_excel_exists()
    try:
        excel_data = pd.read_excel(FILE_PATH, sheet_name=None, engine='openpyxl')
        if group_name in excel_data:
            return False  # уже есть

        # создаём пустой лист с колонками
        excel_data[group_name] = pd.DataFrame(columns=['ИМЯ', 'ФАМИЛИЯ'])
        with pd.ExcelWriter(FILE_PATH, engine='openpyxl') as writer:
            for sheet_name, sheet_df in excel_data.items():
                sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
        return True
    except Exception as e:
        print(f"Ошибка ensure_group_sheet('{group_name}'): {e}")
        raise