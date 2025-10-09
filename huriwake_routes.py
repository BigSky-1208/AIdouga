from flask import Blueprint, render_template, jsonify, session, request, current_app
import io

from googleapiclient.http import MediaIoBaseDownload

# app.pyから共有オブジェクトと関数をインポート
from app import get_drive_service, requires_auth, CLASSIFICATION_FOLDERS, folder_id_cache

# 'huriwake'という名前でブループリントを作成
huriwake_bp = Blueprint('huriwake', __name__)


def populate_folder_cache(drive_service, parent_id):
    """フォルダIDをキャッシュする関数（huriwake_routes専用）"""
    if parent_id in folder_id_cache: return folder_id_cache[parent_id]

    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    list_params = {
        'q': query, 'supportsAllDrives': True, 'includeItemsFromAllDrives': True,
        'fields': "files(id, name)"
    }
    shared_drive_id = current_app.config.get("SHARED_DRIVE_ID")
    if shared_drive_id:
        list_params.update({'corpora': 'drive', 'driveId': shared_drive_id})
    
    response = drive_service.files().list(**list_params).execute()
    subfolders = {folder['name']: folder['id'] for folder in response.get('files', [])}
    folder_id_cache[parent_id] = subfolders
    return subfolders

@huriwake_bp.route('/huriwake')
@requires_auth
def huriwake_page():
    return render_template('huriwake.html', session=session.get('user'))

def count_files_in_folder(drive_service, folder_id):
    query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false"
    list_params = {'q': query, 'supportsAllDrives': True, 'includeItemsFromAllDrives': True, 'fields': 'files(id)'}
    shared_drive_id = current_app.config.get("SHARED_DRIVE_ID")
    if shared_drive_id:
        list_params.update({'corpora': 'drive', 'driveId': shared_drive_id})
    
    response = drive_service.files().list(**list_params).execute()
    return len(response.get('files', []))

@huriwake_bp.route('/api/folders', methods=['GET'])
@requires_auth
def get_folders_with_counts():
    drive_service = get_drive_service()
    drive_folder_id = current_app.config.get("DRIVE_FOLDER_ID")
    subfolders = populate_folder_cache(drive_service, drive_folder_id)
    
    folder_data = []
    for name in CLASSIFICATION_FOLDERS:
        folder_id = subfolders.get(name)
        if folder_id:
            count = count_files_in_folder(drive_service, folder_id)
            folder_data.append({'name': name, 'id': folder_id, 'count': count})
            
    return jsonify(folder_data)

@huriwake_bp.route('/api/images/<folder_id>', methods=['GET'])
@requires_auth
def get_images_in_folder(folder_id):
    drive_service = get_drive_service()
    query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false"
    list_params = {'q': query, 'supportsAllDrives': True, 'includeItemsFromAllDrives': True, 'fields': 'files(id, name)', 'orderBy': 'createdTime'}
    shared_drive_id = current_app.config.get("SHARED_DRIVE_ID")
    if shared_drive_id:
        list_params.update({'corpora': 'drive', 'driveId': shared_drive_id})

    response = drive_service.files().list(**list_params).execute()
    return jsonify(response.get('files', []))

@huriwake_bp.route('/api/image/<file_id>', methods=['GET'])
@requires_auth
def get_image_data(file_id):
    try:
        drive_service = get_drive_service()
        request = drive_service.files().get_media(fileId=file_id, supportsAllDrives=True)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        fh.seek(0)
        return fh.read(), 200, {'Content-Type': 'image/jpeg'}
    except Exception as e:
        current_app.logger.error(f"Failed to get image data: {e}")
        return jsonify({"error": "画像データの取得に失敗しました。"}), 500

def get_or_create_folder_id(drive_service, parent_id, name):
    subfolders = populate_folder_cache(drive_service, parent_id)
    folder_id = subfolders.get(name)
    if folder_id:
        return folder_id
    
    file_metadata = {'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    create_params = {'body': file_metadata, 'fields': 'id', 'supportsAllDrives': True}
    
    new_folder = drive_service.files().create(**create_params).execute()
    # 新しく作ったフォルダをキャッシュに即時反映
    if parent_id in folder_id_cache:
        folder_id_cache[parent_id][name] = new_folder.get('id')
    return new_folder.get('id')

@huriwake_bp.route('/api/move-image', methods=['POST'])
@requires_auth
def move_image():
    try:
        data = request.json
        file_id = data['file_id']
        source_folder_id = data['source_folder_id']
        action = data['action']
        
        drive_service = get_drive_service()
        drive_folder_id = current_app.config.get("DRIVE_FOLDER_ID")
        
        target_parent_id = None
        if action in ['nouhin', 'fuka']:
            target_folder_name = '納品可能' if action == 'nouhin' else '不可'
            target_parent_id = get_or_create_folder_id(drive_service, source_folder_id, target_folder_name)
        elif action.startswith('cat'):
            cat_index = int(action[3:]) - 1
            if 0 <= cat_index < len(CLASSIFICATION_FOLDERS):
                target_folder_name = CLASSIFICATION_FOLDERS[cat_index]
                subfolders = populate_folder_cache(drive_service, drive_folder_id)
                target_parent_id = subfolders.get(target_folder_name)

        if not target_parent_id:
            raise Exception(f"Target folder for action '{action}' not found.")

        file_details = drive_service.files().get(fileId=file_id, fields='parents', supportsAllDrives=True).execute()
        previous_parents = ",".join(file_details.get('parents'))
        
        drive_service.files().update(
            fileId=file_id,
            addParents=target_parent_id,
            removeParents=previous_parents,
            fields='id, parents',
            supportsAllDrives=True
        ).execute()
        
        return jsonify({"success": True, "message": "ファイルを移動しました。"})
    except Exception as e:
        current_app.logger.error(f"Failed to move file: {e}")
        return jsonify({"error": f"ファイルの移動に失敗しました: {str(e)}"}), 500
