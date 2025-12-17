"""
Storage Helper - Universal S3/MinIO/Local Storage Handler
Add this file to each service directory
"""
import os
import logging
from typing import Optional, BinaryIO
from io import BytesIO

logger = logging.getLogger(__name__)

class StorageClient:
    """Universal storage client supporting S3, MinIO, and local filesystem"""
    
    def __init__(self):
        self.storage_mode = os.getenv("STORAGE_MODE", "local").lower()
        self.bucket_name = os.getenv("S3_BUCKET", "default-bucket")
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.storage_root = os.getenv("STORAGE_ROOT", "/app/storage")
        
        # Initialize appropriate client
        if self.storage_mode == "minio":
            self._init_minio()
        elif self.storage_mode == "s3":
            self._init_s3()
        else:
            self._init_local()
        
        logger.info(f"Storage initialized: mode={self.storage_mode}, bucket={self.bucket_name}")
    
    def _init_minio(self):
        """Initialize MinIO client"""
        try:
            from minio import Minio
            
            endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
            access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
            secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
            secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
            
            self.client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure
            )
            
            # Ensure bucket exists
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Created MinIO bucket: {self.bucket_name}")
            
            logger.info(f"MinIO client initialized: {endpoint}")
        except Exception as e:
            logger.error(f"MinIO initialization failed: {e}")
            logger.warning("Falling back to local storage")
            self.storage_mode = "local"
            self._init_local()
    
    def _init_s3(self):
        """Initialize AWS S3 client"""
        try:
            import boto3
            
            self.client = boto3.client('s3', region_name=self.region)
            logger.info("S3 client initialized")
        except Exception as e:
            logger.error(f"S3 initialization failed: {e}")
            logger.warning("Falling back to local storage")
            self.storage_mode = "local"
            self._init_local()
    
    def _init_local(self):
        """Initialize local filesystem storage"""
        os.makedirs(self.storage_root, exist_ok=True)
        self.client = None
        logger.info(f"Local storage initialized: {self.storage_root}")
    
    def upload_file(self, file_path: str, object_name: str) -> Optional[str]:
        """Upload file to storage"""
        try:
            if self.storage_mode == "minio":
                self.client.fput_object(self.bucket_name, object_name, file_path)
                url = f"http://{os.getenv('MINIO_ENDPOINT', 'localhost:9000')}/{self.bucket_name}/{object_name}"
                logger.info(f"Uploaded to MinIO: {object_name}")
                return url
            
            elif self.storage_mode == "s3":
                self.client.upload_file(file_path, self.bucket_name, object_name)
                url = self.client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': object_name},
                    ExpiresIn=604800
                )
                logger.info(f"Uploaded to S3: {object_name}")
                return url
            
            else:  # local
                dest = os.path.join(self.storage_root, object_name)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                import shutil
                shutil.copy2(file_path, dest)
                logger.info(f"Saved locally: {dest}")
                return dest
        
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return None
    
    def upload_fileobj(self, file_obj: BinaryIO, object_name: str) -> Optional[str]:
        """Upload file object to storage"""
        try:
            if self.storage_mode == "minio":
                # Get file size
                file_obj.seek(0, 2)
                file_size = file_obj.tell()
                file_obj.seek(0)
                
                self.client.put_object(
                    self.bucket_name,
                    object_name,
                    file_obj,
                    file_size
                )
                url = f"http://{os.getenv('MINIO_ENDPOINT', 'localhost:9000')}/{self.bucket_name}/{object_name}"
                logger.info(f"Uploaded to MinIO: {object_name}")
                return url
            
            elif self.storage_mode == "s3":
                self.client.upload_fileobj(file_obj, self.bucket_name, object_name)
                url = self.client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': object_name},
                    ExpiresIn=604800
                )
                logger.info(f"Uploaded to S3: {object_name}")
                return url
            
            else:  # local
                dest = os.path.join(self.storage_root, object_name)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, 'wb') as f:
                    file_obj.seek(0)
                    f.write(file_obj.read())
                logger.info(f"Saved locally: {dest}")
                return dest
        
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return None
    
    def download_file(self, object_name: str, file_path: str) -> bool:
        """Download file from storage"""
        try:
            if self.storage_mode == "minio":
                self.client.fget_object(self.bucket_name, object_name, file_path)
                logger.info(f"Downloaded from MinIO: {object_name}")
                return True
            
            elif self.storage_mode == "s3":
                self.client.download_file(self.bucket_name, object_name, file_path)
                logger.info(f"Downloaded from S3: {object_name}")
                return True
            
            else:  # local
                src = os.path.join(self.storage_root, object_name)
                if os.path.exists(src):
                    import shutil
                    shutil.copy2(src, file_path)
                    logger.info(f"Copied locally: {src}")
                    return True
                return False
        
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False
    
    def put_object(self, object_name: str, data: bytes) -> Optional[str]:
        """Upload bytes data to storage"""
        try:
            if self.storage_mode == "minio":
                data_stream = BytesIO(data)
                self.client.put_object(
                    self.bucket_name,
                    object_name,
                    data_stream,
                    len(data)
                )
                url = f"http://{os.getenv('MINIO_ENDPOINT', 'localhost:9000')}/{self.bucket_name}/{object_name}"
                logger.info(f"Uploaded to MinIO: {object_name}")
                return url
            
            elif self.storage_mode == "s3":
                self.client.put_object(
                    Bucket=self.bucket_name,
                    Key=object_name,
                    Body=data
                )
                url = self.client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': object_name},
                    ExpiresIn=604800
                )
                logger.info(f"Uploaded to S3: {object_name}")
                return url
            
            else:  # local
                dest = os.path.join(self.storage_root, object_name)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, 'wb') as f:
                    f.write(data)
                logger.info(f"Saved locally: {dest}")
                return dest
        
        except Exception as e:
            logger.error(f"Put object failed: {e}")
            return None
    
    def delete_object(self, object_name: str) -> bool:
        """Delete object from storage"""
        try:
            if self.storage_mode == "minio":
                self.client.remove_object(self.bucket_name, object_name)
                logger.info(f"Deleted from MinIO: {object_name}")
                return True
            
            elif self.storage_mode == "s3":
                self.client.delete_object(Bucket=self.bucket_name, Key=object_name)
                logger.info(f"Deleted from S3: {object_name}")
                return True
            
            else:  # local
                path = os.path.join(self.storage_root, object_name)
                if os.path.exists(path):
                    os.remove(path)
                    logger.info(f"Deleted locally: {path}")
                return True
        
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False
    
    def generate_presigned_url(self, object_name: str, expires_in: int = 604800) -> Optional[str]:
        """Generate presigned URL for object access"""
        try:
            if self.storage_mode == "minio":
                from datetime import timedelta
                url = self.client.presigned_get_object(
                    self.bucket_name,
                    object_name,
                    expires=timedelta(seconds=expires_in)
                )
                return url
            
            elif self.storage_mode == "s3":
                url = self.client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.bucket_name, 'Key': object_name},
                    ExpiresIn=expires_in
                )
                return url
            
            else:  # local
                # Return local path
                return os.path.join(self.storage_root, object_name)
        
        except Exception as e:
            logger.error(f"Generate presigned URL failed: {e}")
            return None


# Global storage client instance
storage_client = StorageClient()
