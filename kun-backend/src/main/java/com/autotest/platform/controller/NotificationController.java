package com.autotest.platform.controller;

import com.autotest.platform.dto.ApiResponse;
import com.autotest.platform.dto.NotificationBatchDeleteResultDTO;
import com.autotest.platform.dto.NotificationDTO;
import com.autotest.platform.dto.NotificationFeedDTO;
import com.autotest.platform.dto.NotificationReadAllResultDTO;
import com.autotest.platform.service.NotificationService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/notifications")
@RequiredArgsConstructor
@CrossOrigin(origins = "*")
public class NotificationController {

    private final NotificationService notificationService;

    @GetMapping
    public ResponseEntity<ApiResponse<NotificationFeedDTO>> getNotifications(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(defaultValue = "false") boolean unreadOnly,
            Authentication authentication) {
        if (authentication == null || authentication.getName() == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "Authentication required"));
        }
        NotificationFeedDTO feed = notificationService.getNotifications(authentication.getName(), page, size, unreadOnly);
        return ResponseEntity.ok(ApiResponse.success(feed));
    }

    @PatchMapping("/{id}/read")
    public ResponseEntity<ApiResponse<NotificationDTO>> markAsRead(
            @PathVariable Long id,
            Authentication authentication) {
        if (authentication == null || authentication.getName() == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "Authentication required"));
        }
        NotificationDTO updated = notificationService.markAsRead(authentication.getName(), id);
        return ResponseEntity.ok(ApiResponse.success("通知已标记为已读", updated));
    }

    @PatchMapping("/read-all")
    public ResponseEntity<ApiResponse<NotificationReadAllResultDTO>> markAllAsRead(Authentication authentication) {
        if (authentication == null || authentication.getName() == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "Authentication required"));
        }
        NotificationReadAllResultDTO result = notificationService.markAllAsRead(authentication.getName());
        return ResponseEntity.ok(ApiResponse.success("通知已全部标记为已读", result));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<ApiResponse<Void>> deleteNotification(
            @PathVariable Long id,
            Authentication authentication) {
        if (authentication == null || authentication.getName() == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "Authentication required"));
        }
        notificationService.deleteNotification(authentication.getName(), id);
        return ResponseEntity.ok(ApiResponse.success("通知已删除", null));
    }

    @PostMapping("/batch-delete")
    public ResponseEntity<ApiResponse<NotificationBatchDeleteResultDTO>> deleteNotifications(
            @RequestBody(required = false) BatchDeleteRequest request,
            Authentication authentication) {
        if (authentication == null || authentication.getName() == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .body(ApiResponse.error(401, "Authentication required"));
        }
        List<Long> ids = request != null ? request.getIds() : null;
        NotificationBatchDeleteResultDTO result = notificationService.deleteNotifications(authentication.getName(), ids);
        return ResponseEntity.ok(ApiResponse.success("通知已批量删除", result));
    }

    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class BatchDeleteRequest {
        private List<Long> ids;
    }
}
