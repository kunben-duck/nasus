"""
执行实时数据WebSocket
"""
import json
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
from app.schemas.execution import ExecutionRealtimeData

# 存储活跃的WebSocket连接
class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        # 按执行ID分组的连接
        self.execution_connections: Dict[str, Set[WebSocket]] = {}
        # 全局连接
        self.global_connections: Set[WebSocket] = set()
    
    async def connect_to_execution(self, websocket: WebSocket, execution_id: str):
        """连接到特定执行的WebSocket"""
        await websocket.accept()
        
        if execution_id not in self.execution_connections:
            self.execution_connections[execution_id] = set()
        
        self.execution_connections[execution_id].add(websocket)
    
    def disconnect_from_execution(self, websocket: WebSocket, execution_id: str):
        """断开与特定执行的WebSocket连接"""
        if execution_id in self.execution_connections:
            self.execution_connections[execution_id].discard(websocket)
            
            if not self.execution_connections[execution_id]:
                del self.execution_connections[execution_id]
    
    async def connect_global(self, websocket: WebSocket):
        """连接到全局WebSocket"""
        await websocket.accept()
        self.global_connections.add(websocket)
    
    def disconnect_global(self, websocket: WebSocket):
        """断开全局WebSocket连接"""
        self.global_connections.discard(websocket)
    
    async def send_to_execution(self, execution_id: str, message: dict):
        """发送消息到特定执行的所有连接"""
        if execution_id in self.execution_connections:
            disconnected = []
            for connection in self.execution_connections[execution_id]:
                try:
                    await connection.send_json(message)
                except:
                    disconnected.append(connection)
            
            # 清理断开的连接
            for conn in disconnected:
                self.execution_connections[execution_id].discard(conn)
    
    async def broadcast_to_global(self, message: dict):
        """广播消息到所有全局连接"""
        disconnected = []
        for connection in self.global_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)
        
        # 清理断开的连接
        for conn in disconnected:
            self.global_connections.discard(conn)
    
    async def send_execution_update(self, execution_id: str, data: ExecutionRealtimeData):
        """发送执行更新"""
        message = {
            "type": "execution_update",
            "execution_id": execution_id,
            "data": {
                "status": data.status,
                "current_step": data.current_step,
                "total_steps": data.total_steps,
                "progress": data.progress,
                "step_result": data.step_result.model_dump() if data.step_result else None,
                "output": data.output,
                "timestamp": data.timestamp.isoformat() if data.timestamp else None
            }
        }
        await self.send_to_execution(execution_id, message)
        await self.broadcast_to_global(message)


# 全局连接管理器实例
manager = ConnectionManager()


async def execution_websocket_endpoint(websocket: WebSocket, execution_id: str):
    """
    执行WebSocket端点
    
    客户端连接后，可以实时接收执行状态更新
    """
    await manager.connect_to_execution(websocket, execution_id)
    
    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理客户端消息
            if message.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
            
    except WebSocketDisconnect:
        manager.disconnect_from_execution(websocket, execution_id)


async def global_websocket_endpoint(websocket: WebSocket):
    """
    全局WebSocket端点
    
    接收所有执行的状态更新
    """
    await manager.connect_global(websocket)
    
    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理客户端消息
            if message.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
            
    except WebSocketDisconnect:
        manager.disconnect_global(websocket)
