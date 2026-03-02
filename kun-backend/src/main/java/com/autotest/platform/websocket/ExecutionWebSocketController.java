package com.autotest.platform.websocket;

import com.autotest.platform.dto.TestExecutionDTO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.messaging.handler.annotation.SendTo;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Controller;

@Controller
@RequiredArgsConstructor
@Slf4j
public class ExecutionWebSocketController {
    
    private final SimpMessagingTemplate messagingTemplate;
    
    @MessageMapping("/execution/subscribe")
    @SendTo("/topic/executions")
    public ExecutionMessage subscribeToExecutions(@Payload SubscribeMessage message) {
        log.info("Client subscribed to execution updates: {}", message.getExecutionId());
        return ExecutionMessage.builder()
                .type("SUBSCRIBED")
                .executionId(message.getExecutionId())
                .message("Subscribed to execution updates")
                .build();
    }
    
    @MessageMapping("/execution/status")
    @SendTo("/topic/executions")
    public ExecutionMessage updateExecutionStatus(@Payload ExecutionStatusUpdate update) {
        log.info("Execution status update: {} - {}", update.getExecutionId(), update.getStatus());
        return ExecutionMessage.builder()
                .type("STATUS_UPDATE")
                .executionId(update.getExecutionId())
                .status(update.getStatus())
                .progress(update.getProgress())
                .message(update.getMessage())
                .build();
    }
    
    public void sendExecutionUpdate(String executionId, TestExecutionDTO.ExecutionStatus status, 
                                     Integer progress, String message) {
        ExecutionMessage update = ExecutionMessage.builder()
                .type("STATUS_UPDATE")
                .executionId(executionId)
                .status(status != null ? status.name() : null)
                .progress(progress)
                .message(message)
                .timestamp(System.currentTimeMillis())
                .build();
        
        messagingTemplate.convertAndSend("/topic/executions/" + executionId, update);
        messagingTemplate.convertAndSend("/topic/executions", update);
    }
    
    public void sendTimelineUpdate(String executionId, TestExecutionDTO.ExecutionTimelineDTO timeline) {
        TimelineMessage message = TimelineMessage.builder()
                .type("TIMELINE_UPDATE")
                .executionId(executionId)
                .timeline(timeline)
                .timestamp(System.currentTimeMillis())
                .build();
        
        messagingTemplate.convertAndSend("/topic/executions/" + executionId + "/timeline", message);
    }
    
    public void sendScreenshotUpdate(String executionId, TestExecutionDTO.ExecutionScreenshotDTO screenshot) {
        ScreenshotMessage message = ScreenshotMessage.builder()
                .type("SCREENSHOT")
                .executionId(executionId)
                .screenshot(screenshot)
                .timestamp(System.currentTimeMillis())
                .build();
        
        messagingTemplate.convertAndSend("/topic/executions/" + executionId + "/screenshots", message);
    }
    
    // Message DTOs
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class SubscribeMessage {
        private String executionId;
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class ExecutionStatusUpdate {
        private String executionId;
        private String status;
        private Integer progress;
        private String message;
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class ExecutionMessage {
        private String type;
        private String executionId;
        private String status;
        private Integer progress;
        private String message;
        private Long timestamp;
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class TimelineMessage {
        private String type;
        private String executionId;
        private TestExecutionDTO.ExecutionTimelineDTO timeline;
        private Long timestamp;
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class ScreenshotMessage {
        private String type;
        private String executionId;
        private TestExecutionDTO.ExecutionScreenshotDTO screenshot;
        private Long timestamp;
    }
}
