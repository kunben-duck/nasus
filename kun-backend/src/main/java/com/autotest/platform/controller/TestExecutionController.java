package com.autotest.platform.controller;

import com.autotest.platform.dto.ApiResponse;
import com.autotest.platform.dto.PageResponse;
import com.autotest.platform.dto.TestExecutionDTO;
import com.autotest.platform.entity.TestExecution;
import com.autotest.platform.service.TestExecutionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.PathResource;
import org.springframework.core.io.Resource;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/executions")
@RequiredArgsConstructor
@Slf4j
@CrossOrigin(origins = "*")
public class TestExecutionController {
    
    private final TestExecutionService testExecutionService;
    
    @GetMapping
    public ResponseEntity<ApiResponse<PageResponse<TestExecutionDTO>>> getAllExecutions(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(defaultValue = "createdAt,desc") String[] sort) {
        
        Pageable pageable = PageRequest.of(page, size, Sort.by(sort[0]).descending());
        PageResponse<TestExecutionDTO> executions = PageResponse.from(testExecutionService.getAllExecutions(pageable));
        return ResponseEntity.ok(ApiResponse.success(executions));
    }
    
    @GetMapping("/{id}")
    public ResponseEntity<ApiResponse<TestExecutionDTO>> getExecutionById(@PathVariable Long id) {
        TestExecutionDTO execution = testExecutionService.getExecutionById(id);
        return ResponseEntity.ok(ApiResponse.success(execution));
    }
    
    @GetMapping("/execution-id/{executionId}")
    public ResponseEntity<ApiResponse<TestExecutionDTO>> getExecutionByExecutionId(@PathVariable String executionId) {
        TestExecutionDTO execution = testExecutionService.getExecutionByExecutionId(executionId);
        return ResponseEntity.ok(ApiResponse.success(execution));
    }

    @GetMapping("/{id}/artifacts/{*artifactPath}")
    public ResponseEntity<Resource> getExecutionArtifact(
            @PathVariable Long id,
            @PathVariable String artifactPath) {
        TestExecutionService.ExecutionArtifact artifact = testExecutionService.resolveArtifact(id, artifactPath);
        MediaType mediaType = MediaType.APPLICATION_OCTET_STREAM;
        try {
            mediaType = MediaType.parseMediaType(artifact.contentType());
        } catch (Exception ignored) {
            // fallback keep octet-stream
        }

        return ResponseEntity.ok()
                .cacheControl(CacheControl.noCache())
                .contentType(mediaType)
                .header(HttpHeaders.CONTENT_DISPOSITION, "inline; filename=\"" + artifact.fileName() + "\"")
                .body(new PathResource(artifact.filePath()));
    }
    
    @GetMapping("/test-case/{testCaseId}")
    public ResponseEntity<ApiResponse<List<TestExecutionDTO>>> getExecutionsByTestCase(@PathVariable Long testCaseId) {
        List<TestExecutionDTO> executions = testExecutionService.getExecutionsByTestCase(testCaseId);
        return ResponseEntity.ok(ApiResponse.success(executions));
    }
    
    @GetMapping("/status/{status}")
    public ResponseEntity<ApiResponse<PageResponse<TestExecutionDTO>>> getExecutionsByStatus(
            @PathVariable TestExecution.ExecutionStatus status,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        
        Pageable pageable = PageRequest.of(page, size);
        PageResponse<TestExecutionDTO> executions = PageResponse.from(
                testExecutionService.getExecutionsByStatus(status, pageable));
        return ResponseEntity.ok(ApiResponse.success(executions));
    }
    
    @PostMapping
    public ResponseEntity<ApiResponse<TestExecutionDTO>> createExecution(
            @RequestBody TestExecutionDTO.CreateRequest request,
            Authentication authentication) {
        
        TestExecutionDTO createdExecution = testExecutionService.createExecution(request, authentication.getName());
        return ResponseEntity.ok(ApiResponse.success("Execution queued", createdExecution));
    }
    
    @PostMapping("/{id}/start")
    public ResponseEntity<ApiResponse<TestExecutionDTO>> startExecution(@PathVariable Long id) {
        TestExecutionDTO execution = testExecutionService.startExecution(id);
        return ResponseEntity.ok(ApiResponse.success("Execution started", execution));
    }
    
    @PostMapping("/{id}/complete")
    public ResponseEntity<ApiResponse<TestExecutionDTO>> completeExecution(
            @PathVariable Long id,
            @RequestBody CompleteExecutionRequest request) {
        
        TestExecutionDTO execution = testExecutionService.completeExecution(
                id, request.getResult(), request.getLogs());
        return ResponseEntity.ok(ApiResponse.success("Execution completed", execution));
    }
    
    @PostMapping("/{id}/fail")
    public ResponseEntity<ApiResponse<TestExecutionDTO>> failExecution(
            @PathVariable Long id,
            @RequestBody FailExecutionRequest request) {
        
        TestExecutionDTO execution = testExecutionService.failExecution(id, request.getErrorMessage());
        return ResponseEntity.ok(ApiResponse.success("Execution marked as failed", execution));
    }
    
    @PostMapping("/{id}/cancel")
    public ResponseEntity<ApiResponse<Void>> cancelExecution(@PathVariable Long id) {
        testExecutionService.cancelExecution(id);
        return ResponseEntity.ok(ApiResponse.success("Execution cancelled", null));
    }
    
    @GetMapping("/recent")
    public ResponseEntity<ApiResponse<List<TestExecutionDTO>>> getRecentExecutions(
            @RequestParam(defaultValue = "10") int limit) {
        
        List<TestExecutionDTO> executions = testExecutionService.getRecentExecutions(limit);
        return ResponseEntity.ok(ApiResponse.success(executions));
    }
    
    @GetMapping("/stats")
    public ResponseEntity<ApiResponse<ExecutionStats>> getExecutionStats() {
        long total = testExecutionService.countExecutions();
        long pending = testExecutionService.countByStatus(TestExecution.ExecutionStatus.PENDING);
        long running = testExecutionService.countByStatus(TestExecution.ExecutionStatus.RUNNING);
        long completed = testExecutionService.countByStatus(TestExecution.ExecutionStatus.COMPLETED);
        long failed = testExecutionService.countByStatus(TestExecution.ExecutionStatus.FAILED);
        long passCount = testExecutionService.countByResult(TestExecution.ExecutionResult.PASS);
        
        double successRate = total > 0 ? (double) passCount / total * 100 : 0;
        Double avgTime = testExecutionService.getAverageExecutionTime();
        
        ExecutionStats stats = ExecutionStats.builder()
                .total(total)
                .pending(pending)
                .running(running)
                .completed(completed)
                .failed(failed)
                .successRate(Math.round(successRate * 100.0) / 100.0)
                .averageExecutionTime(avgTime != null ? Math.round(avgTime / 1000.0 * 100.0) / 100.0 : 0)
                .build();
        
        return ResponseEntity.ok(ApiResponse.success(stats));
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class CompleteExecutionRequest {
        private TestExecution.ExecutionResult result;
        private String logs;
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class FailExecutionRequest {
        private String errorMessage;
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class ExecutionStats {
        private long total;
        private long pending;
        private long running;
        private long completed;
        private long failed;
        private double successRate;
        private double averageExecutionTime;
    }
}
