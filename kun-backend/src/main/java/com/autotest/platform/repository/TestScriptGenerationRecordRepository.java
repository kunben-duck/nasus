package com.autotest.platform.repository;

import com.autotest.platform.entity.TestScriptGenerationRecord;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface TestScriptGenerationRecordRepository extends JpaRepository<TestScriptGenerationRecord, Long> {

    @Query("""
            SELECT r
            FROM TestScriptGenerationRecord r
            WHERE r.tenantId = :tenantId
              AND r.testCase.id = :testCaseId
            ORDER BY r.createdAt DESC
            """)
    Page<TestScriptGenerationRecord> findByTenantAndTestCase(@Param("tenantId") Long tenantId,
                                                             @Param("testCaseId") Long testCaseId,
                                                             Pageable pageable);

    Optional<TestScriptGenerationRecord> findFirstByTenantIdAndTestCase_IdOrderByCreatedAtDesc(Long tenantId,
                                                                                                Long testCaseId);

    Optional<TestScriptGenerationRecord> findByTenantIdAndTestCase_IdAndRecordId(Long tenantId,
                                                                                 Long testCaseId,
                                                                                 String recordId);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            UPDATE TestScriptGenerationRecord r
               SET r.testScript = null
             WHERE r.tenantId = :tenantId
               AND r.testScript.id = :scriptId
            """)
    int clearScriptReferenceByScriptId(@Param("tenantId") Long tenantId, @Param("scriptId") Long scriptId);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            UPDATE TestScriptGenerationRecord r
               SET r.testScript = null
             WHERE r.tenantId = :tenantId
               AND r.testCase.id = :testCaseId
               AND r.testScript IS NOT NULL
            """)
    int clearScriptReferenceByTestCaseId(@Param("tenantId") Long tenantId, @Param("testCaseId") Long testCaseId);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            UPDATE TestScriptGenerationRecord r
               SET r.testScript = null
             WHERE r.tenantId = :tenantId
               AND r.testCase.userStory.id = :userStoryId
               AND r.testScript IS NOT NULL
            """)
    int clearScriptReferenceByUserStoryId(@Param("tenantId") Long tenantId, @Param("userStoryId") Long userStoryId);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            DELETE FROM TestScriptGenerationRecord r
             WHERE r.tenantId = :tenantId
               AND r.testCase.id = :testCaseId
            """)
    int deleteByTenantIdAndTestCaseId(@Param("tenantId") Long tenantId, @Param("testCaseId") Long testCaseId);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("""
            DELETE FROM TestScriptGenerationRecord r
             WHERE r.tenantId = :tenantId
               AND r.testCase.userStory.id = :userStoryId
            """)
    int deleteByTenantIdAndUserStoryId(@Param("tenantId") Long tenantId, @Param("userStoryId") Long userStoryId);
}
