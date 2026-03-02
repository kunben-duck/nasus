package com.autotest.platform.controller;

import com.autotest.platform.dto.ApiResponse;
import com.autotest.platform.dto.PageResponse;
import com.autotest.platform.dto.TestCaseDTO;
import com.autotest.platform.entity.TestCase;
import com.autotest.platform.service.TestCaseService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/test-cases")
@RequiredArgsConstructor
@Slf4j
@CrossOrigin(origins = "*")
public class TestCaseController {
    
    private final TestCaseService testCaseService;
    
    @GetMapping
    public ResponseEntity<ApiResponse<PageResponse<TestCaseDTO>>> getAllTestCases(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) TestCase.Status status,
            @RequestParam(required = false) TestCase.TestType type,
            @RequestParam(required = false) TestCase.Priority priority,
            @RequestParam(defaultValue = "createdAt,desc") String[] sort) {

        String sortField = "createdAt";
        Sort.Direction direction = Sort.Direction.DESC;
        if (sort.length > 0 && sort[0] != null && !sort[0].isBlank()) {
            String firstSort = sort[0];
            if (firstSort.contains(",")) {
                String[] split = firstSort.split(",");
                if (split.length > 0 && !split[0].isBlank()) {
                    sortField = split[0].trim();
                }
                if (split.length > 1 && "asc".equalsIgnoreCase(split[1].trim())) {
                    direction = Sort.Direction.ASC;
                }
            } else {
                sortField = firstSort.trim();
            }
        }
        if (sort.length > 1 && "asc".equalsIgnoreCase(sort[1])) {
            direction = Sort.Direction.ASC;
        }
        Pageable pageable = PageRequest.of(page, size, Sort.by(direction, sortField));

        String normalizedKeyword = keyword == null ? null : keyword.trim();
        if (normalizedKeyword != null && normalizedKeyword.isEmpty()) {
            normalizedKeyword = null;
        }

        boolean hasFilters = normalizedKeyword != null || status != null || type != null || priority != null;
        PageResponse<TestCaseDTO> testCases = hasFilters
                ? PageResponse.from(testCaseService.getTestCasesByFilters(normalizedKeyword, status, type, priority, pageable))
                : PageResponse.from(testCaseService.getAllTestCases(pageable));
        return ResponseEntity.ok(ApiResponse.success(testCases));
    }
    
    @GetMapping("/{id}")
    public ResponseEntity<ApiResponse<TestCaseDTO>> getTestCaseById(@PathVariable Long id) {
        TestCaseDTO testCase = testCaseService.getTestCaseById(id);
        return ResponseEntity.ok(ApiResponse.success(testCase));
    }
    
    @GetMapping("/number/{caseNumber}")
    public ResponseEntity<ApiResponse<TestCaseDTO>> getTestCaseByNumber(@PathVariable String caseNumber) {
        TestCaseDTO testCase = testCaseService.getTestCaseByNumber(caseNumber);
        return ResponseEntity.ok(ApiResponse.success(testCase));
    }
    
    @GetMapping("/search")
    public ResponseEntity<ApiResponse<PageResponse<TestCaseDTO>>> searchTestCases(
            @RequestParam String keyword,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        
        Pageable pageable = PageRequest.of(page, size);
        PageResponse<TestCaseDTO> testCases = PageResponse.from(testCaseService.searchTestCases(keyword, pageable));
        return ResponseEntity.ok(ApiResponse.success(testCases));
    }
    
    @GetMapping("/user-story/{usId}")
    public ResponseEntity<ApiResponse<List<TestCaseDTO>>> getTestCasesByUserStory(@PathVariable Long usId) {
        List<TestCaseDTO> testCases = testCaseService.getTestCasesByUserStory(usId);
        return ResponseEntity.ok(ApiResponse.success(testCases));
    }
    
    @GetMapping("/status/{status}")
    public ResponseEntity<ApiResponse<PageResponse<TestCaseDTO>>> getTestCasesByStatus(
            @PathVariable TestCase.Status status,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        
        Pageable pageable = PageRequest.of(page, size);
        PageResponse<TestCaseDTO> testCases = PageResponse.from(testCaseService.getTestCasesByStatus(status, pageable));
        return ResponseEntity.ok(ApiResponse.success(testCases));
    }
    
    @PostMapping
    public ResponseEntity<ApiResponse<TestCaseDTO>> createTestCase(
            @RequestBody TestCaseDTO.CreateRequest request,
            Authentication authentication) {
        
        TestCaseDTO createdTC = testCaseService.createTestCase(request, authentication.getName());
        return ResponseEntity.ok(ApiResponse.success("Test Case created", createdTC));
    }
    
    @PutMapping("/{id}")
    public ResponseEntity<ApiResponse<TestCaseDTO>> updateTestCase(
            @PathVariable Long id,
            @RequestBody TestCaseDTO.UpdateRequest request) {
        
        TestCaseDTO updatedTC = testCaseService.updateTestCase(id, request);
        return ResponseEntity.ok(ApiResponse.success("Test Case updated", updatedTC));
    }
    
    @DeleteMapping("/{id}")
    public ResponseEntity<ApiResponse<Void>> deleteTestCase(@PathVariable Long id) {
        testCaseService.deleteTestCase(id);
        return ResponseEntity.ok(ApiResponse.success("Test Case deleted", null));
    }
    
    @GetMapping("/stats")
    public ResponseEntity<ApiResponse<TestCaseStats>> getTestCaseStats() {
        TestCaseStats stats = TestCaseStats.builder()
                .total(testCaseService.countTestCases())
                .draft(testCaseService.countByStatus(TestCase.Status.DRAFT))
                .review(testCaseService.countByStatus(TestCase.Status.REVIEW))
                .ready(testCaseService.countByStatus(TestCase.Status.READY))
                .build();
        return ResponseEntity.ok(ApiResponse.success(stats));
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class TestCaseStats {
        private long total;
        private long draft;
        private long review;
        private long ready;
    }
}
