"""
文件存储服务 - MinIO
"""
import io
from typing import Optional, BinaryIO
from minio import Minio
from minio.error import S3Error
from app.core.config import settings


class StorageService:
    """存储服务类"""
    
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        self.bucket_name = settings.MINIO_BUCKET_NAME
        self._ensure_bucket()
    
    def _ensure_bucket(self):
        """确保存储桶存在"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
        except S3Error as e:
            print(f"创建存储桶失败: {e}")
    
    async def upload_file(self, file_data: bytes, object_name: str, 
                          content_type: str = "application/octet-stream") -> str:
        """
        上传文件
        
        Args:
            file_data: 文件数据
            object_name: 对象名称（路径）
            content_type: 内容类型
            
        Returns:
            文件URL
        """
        try:
            # 上传文件
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=io.BytesIO(file_data),
                length=len(file_data),
                content_type=content_type
            )
            
            # 返回URL
            return f"/{self.bucket_name}/{object_name}"
        except S3Error as e:
            raise Exception(f"上传文件失败: {e}")
    
    async def download_file(self, object_name: str) -> bytes:
        """
        下载文件
        
        Args:
            object_name: 对象名称
            
        Returns:
            文件数据
        """
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            return response.read()
        except S3Error as e:
            raise Exception(f"下载文件失败: {e}")
    
    async def delete_file(self, object_name: str) -> bool:
        """
        删除文件
        
        Args:
            object_name: 对象名称
            
        Returns:
            是否成功
        """
        try:
            self.client.remove_object(self.bucket_name, object_name)
            return True
        except S3Error as e:
            print(f"删除文件失败: {e}")
            return False
    
    async def get_presigned_url(self, object_name: str, expires: int = 3600) -> str:
        """
        获取预签名URL
        
        Args:
            object_name: 对象名称
            expires: 过期时间（秒）
            
        Returns:
            预签名URL
        """
        try:
            return self.client.presigned_get_object(
                self.bucket_name, 
                object_name, 
                expires=expires
            )
        except S3Error as e:
            raise Exception(f"获取预签名URL失败: {e}")
    
    def get_object_path(self, object_type: str, object_id: str, filename: str) -> str:
        """
        获取对象路径
        
        Args:
            object_type: 对象类型（screenshots, videos, logs, reports）
            object_id: 对象ID
            filename: 文件名
            
        Returns:
            完整路径
        """
        from datetime import datetime
        date_path = datetime.now().strftime("%Y/%m/%d")
        return f"{object_type}/{date_path}/{object_id}/{filename}"


# 全局存储服务实例
storage_service = StorageService()
