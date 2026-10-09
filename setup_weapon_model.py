"""下载并校验固定版本的本地简繁英武器名称模型。"""
from weapon_reader import ensure_model, MODEL_URL, MODEL_SHA

if __name__=='__main__':
    path=ensure_model()
    print(f'模型: {path}\n来源: {MODEL_URL}\nSHA256: {MODEL_SHA}')
